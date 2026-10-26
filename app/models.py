from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)
    # "superadmin" | "teacher"
    role = Column(String, nullable=False, default="teacher")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Subject(Base):
    __tablename__ = "subjects"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)

    tests = relationship(
        "Test", back_populates="subject", cascade="all, delete-orphan"
    )


class Test(Base):
    __tablename__ = "tests"

    id = Column(Integer, primary_key=True)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    title = Column(String, nullable=False)

    # draft -> lobby -> active -> finished
    status = Column(String, nullable=False, default="draft")
    code = Column(String, nullable=True)
    current_question_index = Column(Integer, nullable=False, default=0)
    # "answering" | "revealed"
    question_phase = Column(String, nullable=False, default="answering")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    subject = relationship("Subject", back_populates="tests")
    questions = relationship(
        "Question",
        back_populates="test",
        cascade="all, delete-orphan",
        order_by="Question.order",
    )
    participants = relationship(
        "Participant", back_populates="test", cascade="all, delete-orphan"
    )


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True)
    test_id = Column(Integer, ForeignKey("tests.id"), nullable=False)
    text = Column(Text, nullable=False)
    order = Column(Integer, nullable=False, default=0)
    time_limit = Column(Integer, nullable=False, default=30)

    test = relationship("Test", back_populates="questions")
    options = relationship(
        "Option", back_populates="question", cascade="all, delete-orphan"
    )


class Option(Base):
    __tablename__ = "options"

    id = Column(Integer, primary_key=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    text = Column(Text, nullable=False)
    is_correct = Column(Boolean, nullable=False, default=False)

    question = relationship("Question", back_populates="options")


class Participant(Base):
    __tablename__ = "participants"

    id = Column(Integer, primary_key=True)
    test_id = Column(Integer, ForeignKey("tests.id"), nullable=False)
    name = Column(String, nullable=False)
    score = Column(Integer, nullable=False, default=0)
    joined_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    test = relationship("Test", back_populates="participants")
    answers = relationship(
        "Answer", back_populates="participant", cascade="all, delete-orphan"
    )


class Answer(Base):
    __tablename__ = "answers"

    id = Column(Integer, primary_key=True)
    participant_id = Column(Integer, ForeignKey("participants.id"), nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    option_id = Column(Integer, ForeignKey("options.id"), nullable=True)
    is_correct = Column(Boolean, nullable=False, default=False)
    points = Column(Integer, nullable=False, default=0)
    answered_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    participant = relationship("Participant", back_populates="answers")
