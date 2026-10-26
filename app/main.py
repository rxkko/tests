import random
from pathlib import Path

from fastapi import (
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import models
from .database import Base, SessionLocal, engine, get_db
from .ws import manager

Base.metadata.create_all(bind=engine)

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Учебные тесты")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# --------------------------------------------------------------------------- #
# Вспомогательные функции
# --------------------------------------------------------------------------- #
def generate_code(db: Session) -> str:
    """Шестизначный код, уникальный среди запущенных тестов."""
    while True:
        code = str(random.randint(100000, 999999))
        exists = (
            db.query(models.Test)
            .filter(
                models.Test.code == code,
                models.Test.status.in_(["lobby", "active"]),
            )
            .first()
        )
        if not exists:
            return code


def ordered_questions(test: models.Test):
    return sorted(test.questions, key=lambda q: q.order)


def serialize_options(question: models.Question, for_teacher: bool = False):
    opts = []
    for o in question.options:
        item = {"id": o.id, "text": o.text}
        if for_teacher:
            item["is_correct"] = o.is_correct
        opts.append(item)
    return opts


def serialize_question(question: models.Question, for_teacher: bool = False):
    return {
        "id": question.id,
        "text": question.text,
        "time_limit": question.time_limit,
        "options": serialize_options(question, for_teacher),
    }


def student_question_payload(question: models.Question, index: int, total: int):
    return {
        "type": "question",
        "index": index,
        "total": total,
        "text": question.text,
        "time_limit": question.time_limit,
        "options": [{"id": o.id, "text": o.text} for o in question.options],
    }


def participants_payload(db: Session, test: models.Test):
    parts = sorted(test.participants, key=lambda p: p.name.lower())
    return [{"id": p.id, "name": p.name, "score": p.score} for p in parts]


def leaderboard_payload(test: models.Test):
    parts = sorted(test.participants, key=lambda p: (-p.score, p.name.lower()))
    return [{"id": p.id, "name": p.name, "score": p.score} for p in parts]


def get_test_or_404(db: Session, test_id: int) -> models.Test:
    test = db.get(models.Test, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Тест не найден")
    return test


# --------------------------------------------------------------------------- #
# Страницы преподавателя
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    subjects = db.query(models.Subject).order_by(models.Subject.name).all()
    return templates.TemplateResponse(
        request, "index.html", {"subjects": subjects}
    )


@app.post("/subjects")
def create_subject(name: str = Form(...), db: Session = Depends(get_db)):
    name = name.strip()
    if not name:
        return RedirectResponse("/", status_code=303)
    subject = models.Subject(name=name)
    db.add(subject)
    db.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/subjects/{subject_id}", response_class=HTMLResponse)
def subject_detail(subject_id: int, request: Request, db: Session = Depends(get_db)):
    subject = db.get(models.Subject, subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail="Предмет не найден")
    tests = (
        db.query(models.Test)
        .filter(models.Test.subject_id == subject_id)
        .order_by(models.Test.id.desc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "subject.html",
        {"subject": subject, "tests": tests},
    )


@app.post("/subjects/{subject_id}/tests")
def create_test(subject_id: int, title: str = Form(...), db: Session = Depends(get_db)):
    subject = db.get(models.Subject, subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail="Предмет не найден")
    title = title.strip()
    if not title:
        return RedirectResponse(f"/subjects/{subject_id}", status_code=303)
    test = models.Test(subject_id=subject_id, title=title, status="draft")
    db.add(test)
    db.commit()
    return RedirectResponse(f"/tests/{test.id}/edit", status_code=303)


@app.get("/tests/{test_id}/edit", response_class=HTMLResponse)
def test_editor(test_id: int, request: Request, db: Session = Depends(get_db)):
    test = get_test_or_404(db, test_id)
    return templates.TemplateResponse(
        request, "test_editor.html", {"test": test}
    )


class OptionIn(BaseModel):
    text: str
    is_correct: bool = False


class QuestionIn(BaseModel):
    text: str
    time_limit: int = 30
    options: list[OptionIn]


@app.post("/tests/{test_id}/questions")
def add_question(test_id: int, payload: QuestionIn, db: Session = Depends(get_db)):
    test = get_test_or_404(db, test_id)
    options = [o for o in payload.options if o.text.strip()]
    if len(options) < 2:
        raise HTTPException(status_code=400, detail="Нужно минимум 2 варианта ответа")
    if not any(o.is_correct for o in options):
        raise HTTPException(status_code=400, detail="Отметьте правильный ответ")

    question = models.Question(
        test_id=test_id,
        text=payload.text.strip(),
        time_limit=max(5, int(payload.time_limit)),
        order=len(ordered_questions(test)),
    )
    db.add(question)
    db.flush()
    for o in options:
        db.add(
            models.Option(
                question_id=question.id, text=o.text.strip(), is_correct=o.is_correct
            )
        )
    db.commit()
    return {"ok": True, "question_id": question.id}


@app.post("/tests/{test_id}/questions/{question_id}/delete")
def delete_question(
    test_id: int, question_id: int, db: Session = Depends(get_db)
):
    question = db.get(models.Question, question_id)
    if question and question.test_id == test_id:
        db.delete(question)
        db.commit()
    return RedirectResponse(f"/tests/{test_id}/edit", status_code=303)


@app.post("/tests/{test_id}/delete")
def delete_test(test_id: int, db: Session = Depends(get_db)):
    test = db.get(models.Test, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Тест не найден")
    subject_id = test.subject_id
    db.delete(test)
    db.commit()
    return RedirectResponse(f"/subjects/{subject_id}", status_code=303)


@app.post("/tests/{test_id}/start")
def start_test(test_id: int, db: Session = Depends(get_db)):
    test = get_test_or_404(db, test_id)
    if not test.questions:
        return RedirectResponse(f"/tests/{test_id}/edit", status_code=303)
    test.status = "lobby"
    test.code = generate_code(db)
    test.current_question_index = 0
    test.question_phase = "answering"
    for p in list(test.participants):
        db.delete(p)
    db.commit()
    return RedirectResponse(f"/tests/{test_id}/teacher", status_code=303)


@app.get("/tests/{test_id}/teacher", response_class=HTMLResponse)
def teacher_dashboard(test_id: int, request: Request, db: Session = Depends(get_db)):
    test = get_test_or_404(db, test_id)
    return templates.TemplateResponse(
        request, "teacher.html", {"test": test}
    )


# --------------------------------------------------------------------------- #
# Страницы ученика
# --------------------------------------------------------------------------- #
@app.get("/join", response_class=HTMLResponse)
def join_page(request: Request):
    return templates.TemplateResponse(request, "join.html")


@app.post("/join")
async def join(code: str = Form(...), name: str = Form(...), db: Session = Depends(get_db)):
    test = db.query(models.Test).filter(models.Test.code == code.strip()).first()
    if not test or test.status not in ("lobby", "active"):
        raise HTTPException(status_code=400, detail="Код не найден или тест уже завершён")
    name = name.strip()[:30] or "Ученик"
    participant = models.Participant(test_id=test.id, name=name, score=0)
    db.add(participant)
    db.commit()
    await manager.send_to_teachers(
        test.id, {"type": "participants", "participants": participants_payload(db, test)}
    )
    return RedirectResponse(
        f"/student/{test.id}/{participant.id}", status_code=303
    )


@app.get("/student/{test_id}/{participant_id}", response_class=HTMLResponse)
def student_page(
    test_id: int, participant_id: int, request: Request, db: Session = Depends(get_db)
):
    test = db.get(models.Test, test_id)
    participant = db.get(models.Participant, participant_id)
    if not test or not participant or participant.test_id != test_id:
        raise HTTPException(status_code=404, detail="Участник не найден")
    return templates.TemplateResponse(
        request,
        "student.html",
        {"test": test, "participant": participant},
    )


# --------------------------------------------------------------------------- #
# WebSocket: логика викторины
# --------------------------------------------------------------------------- #
async def send_student_state(ws, db, test, participant):
    if test.status == "lobby":
        await ws.send_json(
            {
                "type": "lobby",
                "name": participant.name,
                "participants": [
                    p.name for p in sorted(test.participants, key=lambda x: x.name.lower())
                ],
            }
        )
    elif test.status == "active":
        questions = ordered_questions(test)
        idx = test.current_question_index
        if 0 <= idx < len(questions):
            q = questions[idx]
            await ws.send_json(student_question_payload(q, idx, len(questions)))
            if test.question_phase == "revealed":
                await send_answer_result(ws, db, participant, q)
        else:
            await ws.send_json({"type": "waiting"})
    elif test.status == "finished":
        await ws.send_json(
            {"type": "finished", "leaderboard": leaderboard_payload(test)}
        )
    else:
        await ws.send_json({"type": "closed"})


async def send_answer_result(ws, db, participant, question):
    answer = (
        db.query(models.Answer)
        .filter(
            models.Answer.participant_id == participant.id,
            models.Answer.question_id == question.id,
        )
        .first()
    )
    correct_option = next((o for o in question.options if o.is_correct), None)
    await ws.send_json(
        {
            "type": "answer_result",
            "correct_option_id": correct_option.id if correct_option else None,
            "your_option_id": answer.option_id if answer else None,
            "correct": answer.is_correct if answer else False,
            "points": answer.points if answer else 0,
            "total_score": participant.score,
        }
    )


async def handle_answer(db, test, participant, option_id):
    db.expire_all()
    if test.status != "active" or test.question_phase != "answering":
        return
    questions = ordered_questions(test)
    idx = test.current_question_index
    if not (0 <= idx < len(questions)):
        return
    question = questions[idx]

    existing = (
        db.query(models.Answer)
        .filter(
            models.Answer.participant_id == participant.id,
            models.Answer.question_id == question.id,
        )
        .first()
    )
    if existing:
        return

    option = db.get(models.Option, option_id)
    if not option or option.question_id != question.id:
        return

    is_correct = option.is_correct
    points = 100 if is_correct else 0
    db.add(
        models.Answer(
            participant_id=participant.id,
            question_id=question.id,
            option_id=option.id,
            is_correct=is_correct,
            points=points,
        )
    )
    participant.score += points
    db.commit()

    answered = (
        db.query(models.Answer)
        .join(models.Participant)
        .filter(
            models.Participant.test_id == test.id,
            models.Answer.question_id == question.id,
        )
        .count()
    )
    await manager.send_to_teachers(
        test.id,
        {
            "type": "progress",
            "answered": answered,
            "total": len(test.participants),
            "participants": participants_payload(db, test),
        },
    )


async def send_teacher_state(ws, db, test):
    questions = ordered_questions(test)
    idx = test.current_question_index
    current = None
    if test.status == "active" and 0 <= idx < len(questions):
        current = serialize_question(questions[idx], for_teacher=True)
    await ws.send_json(
        {
            "type": "state",
            "status": test.status,
            "code": test.code,
            "phase": test.question_phase if test.status == "active" else None,
            "index": idx,
            "total": len(questions),
            "question": current,
            "participants": participants_payload(db, test),
        }
    )


async def teacher_start(db, test):
    db.expire_all()
    if test.status != "lobby" or not test.questions:
        return
    for p in test.participants:
        p.score = 0
        for a in list(p.answers):
            db.delete(a)
    test.status = "active"
    test.current_question_index = 0
    test.question_phase = "answering"
    db.commit()

    questions = ordered_questions(test)
    await manager.send_to_students(
        test.id, student_question_payload(questions[0], 0, len(questions))
    )
    await manager.send_to_teachers(
        test.id,
        {
            "type": "question",
            "index": 0,
            "total": len(questions),
            "phase": "answering",
            "question": serialize_question(questions[0], for_teacher=True),
            "participants": participants_payload(db, test),
        },
    )


async def teacher_reveal(db, test):
    db.expire_all()
    if test.status != "active" or test.question_phase != "answering":
        return
    test.question_phase = "revealed"
    db.commit()

    questions = ordered_questions(test)
    q = questions[test.current_question_index]
    correct_option = next((o for o in q.options if o.is_correct), None)
    for p in test.participants:
        answer = (
            db.query(models.Answer)
            .filter(
                models.Answer.participant_id == p.id,
                models.Answer.question_id == q.id,
            )
            .first()
        )
        await manager.send_to_student(
            test.id,
            p.id,
            {
                "type": "answer_result",
                "correct_option_id": correct_option.id if correct_option else None,
                "your_option_id": answer.option_id if answer else None,
                "correct": answer.is_correct if answer else False,
                "points": answer.points if answer else 0,
                "total_score": p.score,
            },
        )
    await manager.send_to_teachers(
        test.id,
        {
            "type": "revealed",
            "question": serialize_question(q, for_teacher=True),
            "participants": participants_payload(db, test),
        },
    )


async def teacher_next(db, test):
    db.expire_all()
    if test.status != "active":
        return
    questions = ordered_questions(test)
    nxt = test.current_question_index + 1
    if nxt >= len(questions):
        return
    test.current_question_index = nxt
    test.question_phase = "answering"
    db.commit()

    q = questions[nxt]
    await manager.send_to_students(
        test.id, student_question_payload(q, nxt, len(questions))
    )
    await manager.send_to_teachers(
        test.id,
        {
            "type": "question",
            "index": nxt,
            "total": len(questions),
            "phase": "answering",
            "question": serialize_question(q, for_teacher=True),
            "participants": participants_payload(db, test),
        },
    )


async def teacher_finish(db, test):
    db.expire_all()
    if test.status != "active":
        return
    test.status = "finished"
    db.commit()
    await manager.broadcast(
        test.id, {"type": "finished", "leaderboard": leaderboard_payload(test)}
    )


async def teacher_restart(db, test):
    db.expire_all()
    if test.status != "finished":
        return
    test.status = "lobby"
    test.code = generate_code(db)
    test.current_question_index = 0
    test.question_phase = "answering"
    for p in list(test.participants):
        db.delete(p)
    db.commit()
    await manager.send_to_students(test.id, {"type": "closed"})
    await manager.send_to_teachers(
        test.id,
        {
            "type": "state",
            "status": "lobby",
            "code": test.code,
            "participants": [],
        },
    )


@app.websocket("/ws/student/{test_id}/{participant_id}")
async def ws_student(websocket: WebSocket, test_id: int, participant_id: int):
    await manager.connect(test_id, "student", participant_id, websocket)
    db = SessionLocal()
    try:
        participant = db.get(models.Participant, participant_id)
        test = db.get(models.Test, test_id)
        if not participant or not test or participant.test_id != test_id:
            await websocket.close()
            return
        await send_student_state(websocket, db, test, participant)
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "answer":
                await handle_answer(db, test, participant, data.get("option_id"))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        manager.disconnect(test_id, websocket)
        db.close()


@app.websocket("/ws/teacher/{test_id}")
async def ws_teacher(websocket: WebSocket, test_id: int):
    await manager.connect(test_id, "teacher", None, websocket)
    db = SessionLocal()
    try:
        test = db.get(models.Test, test_id)
        if not test:
            await websocket.close()
            return
        await send_teacher_state(websocket, db, test)
        while True:
            data = await websocket.receive_json()
            action = data.get("type")
            if action == "start":
                await teacher_start(db, test)
            elif action == "reveal":
                await teacher_reveal(db, test)
            elif action == "next":
                await teacher_next(db, test)
            elif action == "finish":
                await teacher_finish(db, test)
            elif action == "restart":
                await teacher_restart(db, test)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        manager.disconnect(test_id, websocket)
        db.close()
