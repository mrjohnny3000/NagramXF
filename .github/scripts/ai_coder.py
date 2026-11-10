import os
import json
import subprocess
import time
import google.generativeai as genai

api_key = os.getenv("GEMINI_API_KEY")
issue_title = os.getenv("ISSUE_TITLE", "")
issue_body = os.getenv("ISSUE_BODY", "")

if not api_key:
    print("Error: GEMINI_API_KEY not found.")
    exit(1)

genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-3.8-flash")

# Ограничиваем сканирование, чтобы не вылетать за 250k токенов/мин
exclude_dirs = {
    ".git", ".github", "build", ".gradle", ".idea", 
    "gradle", "bin", "out", "libs", "res"  # Исключаем тяжелые ресурсы
}
include_extensions = {".kt", ".java", ".xml"}

codebase = {}
max_file_size_bytes = 60 * 1024  # Пропускаем гигантские файлы >60КБ

print("Scanning repository codebase (optimized)...")
for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if d not in exclude_dirs]
    for file in files:
        ext = os.path.splitext(file)[1]
        if ext in include_extensions:
            path = os.path.join(root, file)
            rel_path = os.path.relpath(path, ".")
            
            # Пропускаем автосгенерированные или слишком большие файлы
            if os.path.getsize(path) > max_file_size_bytes:
                print(f"Skipping heavy file: {rel_path}")
                continue
                
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    codebase[rel_path] = f.read()
            except Exception as e:
                print(f"Skipping {rel_path}: {e}")

print(f"Loaded {len(codebase)} key files into context.")

prompt = f"""
You are an expert Android developer modifying a Telegram client fork (NagramXF).
A user created a GitHub Issue:
Title: {issue_title}
Body: {issue_body}

Project files:
{json.dumps(codebase, indent=2)}

Task: Analyze the issue, modify existing files or create new ones to fulfill the request.
Response format: Return ONLY a valid JSON object mapping relative file paths to complete new file contents. Do NOT use markdown fences like ```json.
Example:
{{
  "TMessagesProj/src/main/java/org/telegram/ui/MyFeature.java": "content..."
}}
"""

print("Sending context to Gemini...")

# Обработка лимитов API с повторной попыткой
for attempt in range(3):
    try:
        response = model.generate_content(prompt)
        text_response = response.text.strip()
        break
    except Exception as e:
        if "429" in str(e) and attempt < 2:
            print("Rate limit reached. Waiting 60 seconds before retrying...")
            time.sleep(60)
        else:
            raise e

if text_response.startswith("```"):
    lines = text_response.splitlines()
    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    text_response = "\n".join(lines).strip()

try:
    changes = json.loads(text_response)
except Exception as e:
    print("Failed to parse JSON response from Gemini:")
    print(text_response)
    exit(1)

print(f"Applying {len(changes)} file changes...")
for path, content in changes.items():
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Updated: {path}")

# Настройка Git и пуш
subprocess.run(["git", "config", "--global", "user.name", "AI Coder Bot"], check=True)
subprocess.run(["git", "config", "--global", "user.email", "ai-bot@users.noreply.github.com"], check=True)

branch_name = f"ai-patch-{os.getenv('GITHUB_RUN_ID', 'fix')}"
subprocess.run(["git", "checkout", "-b", branch_name], check=True)
subprocess.run(["git", "add", "."], check=True)

status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
if not status.stdout.strip():
    print("No changes made by AI.")
    exit(0)

subprocess.run(["git", "commit", "-m", f"AI Fix: {issue_title}"], check=True)
repo_url = f"https://x-access-token:{os.getenv('GITHUB_TOKEN')}@github.com/{os.getenv('GITHUB_REPOSITORY')}.git"
subprocess.run(["git", "push", "origin", branch_name], check=True)
print(f"Pushed branch {branch_name} successfully!")
