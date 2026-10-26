import uvicorn

if __name__ == "__main__":
    # 0.0.0.0 — чтобы ученики могли зайти с телефонов по IP преподавателя
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
