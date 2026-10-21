import pytest
from pydantic import ValidationError


def test_login_preserves_password_and_masks_repr():
    from app.auth_schemas import LoginRequest

    request = LoginRequest(username="alice", password="  abcdef ")
    assert request.password.get_secret_value() == "  abcdef "
    assert "abcdef" not in repr(request)
    assert "abcdef" not in request.model_dump_json()


@pytest.mark.parametrize("password", ["123456", "1234567890"])
def test_password_boundaries(password):
    from app.auth_schemas import LoginRequest

    assert LoginRequest(username="alice", password=password).password.get_secret_value() == password


@pytest.mark.parametrize("payload", [
    {"username": "alice", "password": "12345"},
    {"username": "alice", "password": "12345678901"},
    {"username": "alice", "password": 123456},
    {"username": " alice", "password": "123456"},
    {"username": "alice", "password": "123456", "user_id": "injected"},
])
def test_invalid_login_payload(payload):
    from app.auth_schemas import LoginRequest

    with pytest.raises(ValidationError):
        LoginRequest.model_validate(payload)


def test_identity_excludes_secrets():
    from app.auth_schemas import CurrentUserResponse

    response = CurrentUserResponse(user_id="9aca48bf-6aca-4054-8d10-3199cd285911", username="alice")
    assert set(response.model_dump()) == {"user_id", "username"}
    with pytest.raises(ValidationError):
        CurrentUserResponse(**response.model_dump(), token="private")
