from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    model_validator,
)

type Email = Annotated[
    EmailStr, Field(max_length=120), AfterValidator(lambda v: v.lower())
]


class UserBase(BaseModel):
    username: Annotated[
        str,
        Field(min_length=1, max_length=50),
        AfterValidator(lambda v: v.lower()),
    ]


class UserCreate(UserBase):
    email: Email

    password: Annotated[SecretStr, Field(min_length=8)]
    confirm_password: Annotated[SecretStr, Field(min_length=8)]

    @model_validator(mode="after")
    def passwords_match(self) -> UserCreate:
        if self.password != self.confirm_password:
            raise ValueError("Passwords don't match")

        return self


class UserUpdate(BaseModel):
    username: Annotated[
        str | None,
        Field(default=None, min_length=1, max_length=50),
        AfterValidator(lambda v: v.lower()),
    ]
    email: Annotated[
        EmailStr | None,
        Field(default=None, max_length=120),
        AfterValidator(lambda v: v.lower()),
    ]
    password: Annotated[SecretStr | None, Field(default=None, min_length=8)]

    confirm_password: Annotated[
        SecretStr | None, Field(default=None, min_length=8)
    ]

    @model_validator(mode="after")
    def passwords_match(self) -> UserUpdate:
        is_updating_passwords = all((self.password, self.confirm_password))

        if is_updating_passwords and self.password != self.confirm_password:
            raise ValueError("Passwords don't match")

        return self


class UserPublicResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    image_path: str


class UserPrivateResponse(UserPublicResponse):
    email: Email
