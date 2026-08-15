try:
    import edge_tts, pydub, pydantic, PIL
    print("deps OK")
except Exception as e:
    print("MISSING:", e)
