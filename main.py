from fastapi import FastAPI

app = FastAPI(title="Money Care AI")


@app.get("/health")
def health_check():
    return {"status": "ok"}