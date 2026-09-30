from typing import Annotated

from fastapi import Depends, Header, HTTPException, status


def require_bearer(expected_key: str | None):
    def dependency(authorization: Annotated[str | None, Header()] = None) -> None:
        if not expected_key:
            return
        if authorization != f"Bearer {expected_key}":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token")

    return Depends(dependency)
