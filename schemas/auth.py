from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, SecretStr


class Token(BaseModel):
    access_token: str
    token_type: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr = Field(max_length=120)


class ResetPasswordRequest(BaseModel):
    token: Annotated[SecretStr, Field(min_length=32)]
    new_password: Annotated[SecretStr, Field(min_length=8)]


class ChangePasswordRequest(BaseModel):
    current_password: Annotated[SecretStr, Field(min_length=8)]
    new_password: Annotated[SecretStr, Field(min_length=8)]
