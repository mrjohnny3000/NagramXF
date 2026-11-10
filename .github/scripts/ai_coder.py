import os
import json
import subprocess
import google.generativeai as genai

api_key = os.getenv("GEMINI_API_KEY")
issue_title = os.getenv("ISSUE_TITLE", "")
issue_body = os.getenv("ISSUE_BODY", "")

if not api_key:
    print("Error: GEMINI_API_KEY not found.")
    exit(1)

genai.configure(api_key=api_key)
# Используем модель с огромным контекстом, чтобы влез весь проект
model = genai.GenerativeModel("gemini-1.5-flash")

exclude_dirs = {".git", ".github", "build", ".gradle", ".idea"}
include_extensions = {".kt", ".java", ".xml", ".gradle", ".properties"}

codebase = {}
file_list = []

print("Scanning repository codebase...")
for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if d not in exclude_dirs]
    for file in files:
        ext = os.path.splitext(file)[1]
        if ext in include_extensions:
            path = os.path.join(root, file)
            rel_path = os.path.relpath(path, ".")
            file_list.append(rel_path)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    codebase[rel_path] = f.read()
            except Exception as e:
                print(f"Skipping {rel_path}: {e}")

print(f"Loaded {len(codebase)} files into context.")

prompt = f"""
You are an expert Android developer modifying a Telegram client fork (NagramXF).
A user created a GitHub Issue with the following task:
Title: {issue_title}
Body: {issue_body}

Here is the project file structure and file contents:
{json.dumps(codebase, indent=2)}

Task: Analyze the issue, modify the existing files or create new ones necessary to implement the requested feature or fix the bug.
Response format: You MUST return ONLY a valid JSON object where keys are relative file paths and values are the complete new contents of the modified files. Do not include markdown code block formatting like ```json or any other text outside the JSON object. Example format:
{{
  "TMessagesProj/src/main/java/org/telegram/ui/LaunchActivity.java": "updated content here..."
}}
"""

print("Sending context and prompt to Gemini...")
response = model.generate_content(prompt)
text_response = response.text.strip()

# Очистка от маркдауна на всякий случай
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

# Конфиг гита и пуш в новую ветку
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
# Настраиваем пуш с токеном GITHUB_TOKEN
repo_url = f"https://x-access-token:{os.getenv('GITHUB_TOKEN')}@github.com/{os.getenv('GITHUB_REPOSITORY')}.git"
subprocess.run(["git", "push", "origin", branch_name], check=True)
print(f"Pushed branch {branch_name} successfully!")
