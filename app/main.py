from fastapi import FastAPI

app = FastAPI(title="fifthrow-be")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
