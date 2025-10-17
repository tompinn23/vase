from cx_Freeze import setup, Executable

setup(
    name="Vase",
    version="1.0",
    description="Vase is an Elite Dangerous Journal Processor",
    executables=[Executable("main.py")],
    options={
        "build_exe": {
            "includes": ["win32timezone"],
            "include_files": ["ships.json"]
        }
    }
)