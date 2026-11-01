from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

# starlette gestisce vari errori di fastapi es. quelli di pagina non trovata
from starlette.exceptions import HTTPException as StarletteHTTPException

import models
from config import settings
from database import Database, engine
from routers import auth, posts, users


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        # Crea le tabelle db in modo ASINCRONO
        # da utilizzare senza alembci in quanto
        # non esegue nessun tipo di migrazione (solo creazione)
        # async with engine.begin() as conn:
        #     await conn.run_sync(Base.metadata.create_all)
        yield
    finally:
        await engine.dispose()


# Crea le tabelle db in modo SINCRONO
# Base.metadata.create_all(bind=engine)

# uv add fastapi[standard] per installare ulteriori librerie (extras)
# utili come jinja2 per la costruzione di template dinamici

app = FastAPI(lifespan=lifespan)

app.mount("/static", name="static", app=StaticFiles(directory="static"))
# app.mount("/media", name="media", app=StaticFiles(directory="media"))

# tags=[] permette alle docs autogenerate di suddividere le rotte per sezioni
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(posts.router, prefix="/api/posts", tags=["posts"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])


@app.get("/health")
async def health_check(db: Database):
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc
    return {"status": "healthy"}


# @app.get("/", response_class=HTMLResponse, include_in_schema=False)

# response_class = Decide come l'api deve rispondere (default JSONResponse)
# include_in_schema = escludere la rotta dalle docs
# name = nome della rotta che verra passata a funzioni come url_for
# nei template j2 per mostrare l'url corretto

templates = Jinja2Templates(directory="templates")


@app.get("/login", include_in_schema=False)
async def login_page(request: Request):
    return templates.TemplateResponse(
        request,
        "login.html.j2",
        {"title": "Login"},
    )


@app.get("/register", include_in_schema=False)
async def register_page(request: Request):
    return templates.TemplateResponse(
        request,
        "register.html.j2",
        {"title": "Register"},
    )


@app.get("/account", include_in_schema=False)
async def account_page(request: Request):
    return templates.TemplateResponse(
        request,
        "account.html.j2",
        {"title": "Account"},
    )


@app.get("/forgot-password", include_in_schema=False)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse(
        request,
        "forgot_password.html.j2",
        {"title": "Forgot Password"},
    )


@app.get("/reset-password", include_in_schema=False)
async def reset_password_page(request: Request):
    response = templates.TemplateResponse(
        request,
        "reset_password.html.j2",
        {"title": "Reset Password"},
    )
    # TODO: capire meglio il funzionamento
    # Referrer-Policy: no-referrer impedisce che il reset token esca dalla pagina.
    #
    # Il token sta nell'URL (/reset-password?token=...). Quando una pagina
    # carica una risorsa esterna (font Google, Bootstrap da jsdelivr nel
    # layout) o l'utente clicca un link, il browser puo mandare al sito di
    # destinazione l'header Referer, cioe "da quale URL arrivo". Se dentro
    # quell'URL c'e il token, un sito terzo lo riceve e lo trova nei suoi log.
    # Con no-referrer il browser non manda mai il Referer da questa pagina.
    #
    # Va solo qui perche e' l'unica pagina con un segreto nell'URL.
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/", include_in_schema=False, name="home")
@app.get("/posts", include_in_schema=False, name="posts")
async def home(request: Request, db: Database):
    count_result = await db.execute(
        select(func.count()).select_from(models.Post)
    )
    total = count_result.scalar() or 0

    # Se utilizziamo le sessioni db asincrone dobbiamo manualmente caricare
    # tramite options(selectinload(model)) la relazione da aggregare al modello principale
    result = await db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .order_by(models.Post.date_posted.desc())
        .limit(settings.posts_per_page),
    )
    posts = result.scalars().all()

    has_more = len(posts) < total

    return templates.TemplateResponse(
        request,
        "home.html.j2",
        {
            "posts": posts,
            "title": "Home",
            "limit": settings.posts_per_page,
            "has_more": has_more,
        },
    )


@app.get("/posts/{post_id}", include_in_schema=False)
async def post_page(
    request: Request,
    post_id: int,
    db: Database,
):
    result = await db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .where(models.Post.id == post_id)
    )
    post = result.scalars().first()

    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Post not found"
        )

    return templates.TemplateResponse(
        request,
        name="post.html.j2",
        context={"title": post.title[:50], "post": post},
    )


@app.get("/users/{user_id}/posts", include_in_schema=False)
async def user_posts_page(
    request: Request,
    user_id: int,
    db: Database,
):
    result = await db.execute(
        select(models.User).where(models.User.id == user_id)
    )
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    count_result = await db.execute(
        select(func.count())
        .select_from(models.Post)
        .where(models.Post.user_id == user_id),
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .where(models.Post.user_id == user_id)
        .order_by(models.Post.date_posted.desc())
        .limit(settings.posts_per_page),
    )
    posts = result.scalars().all()

    has_more = len(posts) < total

    return templates.TemplateResponse(
        request,
        "user_posts.html.j2",
        {
            "posts": posts,
            "user": user,
            "title": f"{user.username}'s Posts",
            "limit": settings.posts_per_page,
            "has_more": has_more,
        },
    )


# Exception handlers


# Cattura solo eccezioni di starlette, ovvero pagine non trovate o
# errori lanciati manualmente con HTTPException di fastapi dato che
# e' figlio di StarletteHTTPException
@app.exception_handler(StarletteHTTPException)
async def general_http_exception_handler(
    request: Request, exception: StarletteHTTPException
):

    if request.url.path.startswith("/api"):
        return await http_exception_handler(request, exception)

    message = (
        exception.detail
        if exception.detail
        else "An error occurred. Please check your request and try again."
    )
    return templates.TemplateResponse(
        request,
        "error.html.j2",
        status_code=exception.status_code,
        context={
            "status_code": exception.status_code,
            "title": exception.status_code,
            "message": message,
        },
    )


# Cattura errori di validazione automatici
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exception: RequestValidationError
):
    if request.url.path.startswith("/api"):
        return await request_validation_exception_handler(request, exception)

    return templates.TemplateResponse(
        request,
        "error.html.j2",
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        context={
            "status_code": status.HTTP_422_UNPROCESSABLE_CONTENT,
            "title": status.HTTP_422_UNPROCESSABLE_CONTENT,
            "message": "Invalid request. Please check your input and try again.",
        },
    )
