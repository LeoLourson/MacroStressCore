from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException


class Problem(Exception):
    def __init__(self, status, detail, *, violations=(), headers=None):
        self.status, self.detail = status, detail
        self.violations, self.headers = list(violations), headers or {}


def problem(status, title, detail, violations=(), *, instance=None, headers=None):
    return JSONResponse(
        status_code=status,
        content={
            "type": "about:blank",
            "title": title,
            "status": status,
            "detail": detail,
            "violations": jsonable_encoder(violations),
            "instance": instance,
        },
        media_type="application/problem+json",
        headers=headers,
    )


def install_handlers(app):
    from http import HTTPStatus

    @app.exception_handler(Problem)
    async def domain(request, exc):
        return problem(
            exc.status,
            HTTPStatus(exc.status).phrase,
            exc.detail,
            exc.violations,
            instance=request.url.path,
            headers=exc.headers,
        )

    async def invalid(request, exc):
        violations = [
            {
                "rule_id": "V1",
                "path": "/"
                + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in e["loc"]),
                "message": e["msg"],
            }
            for e in exc.errors()
        ]
        return problem(
            422,
            "Validation failed",
            "Request violates the contract",
            violations,
            instance=request.url.path,
        )

    app.add_exception_handler(RequestValidationError, invalid)
    app.add_exception_handler(ValidationError, invalid)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return problem(
            exc.status_code,
            HTTPStatus(exc.status_code).phrase,
            str(exc.detail),
            instance=request.url.path,
            headers=exc.headers,
        )

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return problem(
            404,
            "Not found",
            "Requested object does not exist in this scope",
            instance=request.url.path,
        )

    @app.exception_handler(PermissionError)
    async def forbidden(request, exc):
        return problem(403, "Forbidden", str(exc), instance=request.url.path)

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return problem(
            422,
            "Validation failed",
            str(exc),
            [{"rule_id": "V1", "path": "", "message": str(exc)}],
            instance=request.url.path,
        )

    @app.exception_handler(Exception)
    async def internal(request, exc):
        import logging

        logging.getLogger(__name__).exception("API operation failed")
        return problem(
            500,
            "Internal Server Error",
            "Operation failed; consult the server log",
            instance=request.url.path,
        )
