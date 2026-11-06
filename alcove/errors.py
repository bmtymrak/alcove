class NoteError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid",
        status: int = 400,
        fields: dict[str, list[str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.fields = fields or {}
