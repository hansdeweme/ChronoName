# Read multiple Python files and combine them into a single text file
with open("chrononame-combined_code.txt", "w", encoding="utf-8") as output_file:
    for filename in ["chrononame.py", 
                     "chrononame_cli.py", 
                     "chrononame_core.py", 
                     "config.py", 
                     "duplicate_core.py", 
                     "exiftool_adapter.py", 
                     "diagnostics_core.py",
                     "filing_audit.py",
                     "main.py", 
                     "models.py", 
                     "report_paths.py", 
                     "timestamp_health.py", 
                     "ui.py", 
                     "whatsapp_core.py", 
                     "workers.py", 
                     "settings.json", 
                     ]:  # List your Python files here
        with open(filename, "r", encoding="utf-8") as input_file:
            content = input_file.read()
            output_file.write(f"--- Start of {filename} ---\n")
            output_file.write(content)
            output_file.write(f"\n--- End of {filename} ---\n\n")
