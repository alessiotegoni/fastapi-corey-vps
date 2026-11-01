from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header, create_test_user, login_user


@pytest.mark.anyio
async def test_create_user_validation_error(client: AsyncClient):
    response = await client.post(
        "/api/users",
        json={
            "username": "",
            "email": "",
            "password": "ciao",
            "confirm_password": "c",
        },
    )

    assert response.status_code == 422

    assert "username" in response.text
    assert "email" in response.text
    assert "password" in response.text
    assert "confirm" in response.text


@pytest.mark.anyio
async def test_create_duplicate_user(client: AsyncClient):
    user = await create_test_user(client)
    response = await client.post(
        "/api/users",
        json={
            "email": user["email"],
            "username": user["username"],
            "password": "12345678",
            "confirm_password": "12345678",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Username or Email already exists"


@pytest.mark.anyio
async def test_create_user_success(client: AsyncClient):
    new_user = {
        "username": "carlodazzi",
        "email": "carlodazzi@gmail.com",
        "password": "12345678",
        "confirm_password": "12345678",
    }

    user = await create_test_user(client, **new_user)

    assert user["email"] == new_user["email"]
    assert user["username"] == new_user["username"]
    assert "id" in user
    assert "image_path" in user
    assert "password" not in user
    assert "confirm_password" not in user
    assert "password_hash" not in user


## Test Upload Profile Picture
@pytest.mark.anyio
async def test_upload_profile_picture(client: AsyncClient, mocked_aws):
    user = await create_test_user(client)
    token = await login_user(client)

    test_image_path = Path(__file__).parent / "test_image.jpg"
    image_bytes = test_image_path.read_bytes()

    response = await client.patch(
        f"/api/users/{user['id']}/picture",
        files={"file": ("profile.jpg", BytesIO(image_bytes), "image/jpeg")},
        headers=auth_header(token),
    )

    assert response.status_code == 200
    data = response.json()

    assert data["image_path"] is not None
    assert data["image_path"].endswith(".jpg")
    assert "s3" in data["image_path"]

    s3_objects = mocked_aws.list_objects_v2(Bucket="test-bucket")
    assert "Contents" in s3_objects
    assert len(s3_objects["Contents"]) == 1
    assert data["image_path"].endswith(s3_objects["Contents"][0]["Key"])


@pytest.mark.anyio
async def test_forgot_password_sends_email(client: AsyncClient):
    await create_test_user(client)

    with patch(
        "routers.auth.send_password_reset_email",
        new_callable=AsyncMock,
    ) as mock_send:
        response = await client.post(
            "/api/auth/forgot-password",
            json={"email": "test@example.com"},
        )

        assert response.status_code == 202
        mock_send.assert_awaited_once()
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["to_email"] == "test@example.com"
        assert call_kwargs["username"] == "testuser"
        assert "token" in call_kwargs
