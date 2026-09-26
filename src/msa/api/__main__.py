import uvicorn


def main():
    # One process owns job recovery. LangGraph runs up to five jobs concurrently inside it.
    uvicorn.run("msa.api.main:app", host="127.0.0.1", port=8091, workers=1)


if __name__ == "__main__":
    main()
