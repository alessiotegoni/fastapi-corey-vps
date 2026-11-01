from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from .users import UserPublicResponse


class PostBase(BaseModel):
    title: Annotated[str, Field(min_length=3)]
    content: Annotated[str, Field(min_length=3)]


class PostCreate(PostBase):
    pass


class PostUpdate(BaseModel):
    title: Annotated[
        str | None, Field(default=None, min_length=3, max_length=100)
    ]
    content: Annotated[
        str | None, Field(default=None, min_length=3, max_length=200)
    ]


class PostResponse(PostBase):
    # from_attributes=True
    # Permette di creare un'istanza di un modello Pydantic
    # partendo da un oggetto ORM (come un record di database di SQLAlchemy o SQLModel)
    # o da qualsiasi oggetto Python arbitrario che utilizzi gli attributi invece dei dizionari.

    # Di default, Pydantic si aspetta che i dati passati per creare un modello siano strutturati
    # come un dizionario (chiave-valore). Se provi a passare un oggetto Python classico,
    # Pydantic fallirà perché cercherà di accedere ai dati usando la sintassi dati['chiave'].
    # Abilitando from_attributes=True, indichi a Pydantic di estrarre i dati leggendo gli
    # attributi dell'oggetto tramite la sintassi dati.chiave
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    date_posted: datetime
    author: UserPublicResponse


class PaginatedPostsResponse(BaseModel):
    posts: list[PostResponse]
    total: int
    skip: int
    limit: int
    has_more: bool
