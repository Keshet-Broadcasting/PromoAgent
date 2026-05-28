"""Run the eval with proper output capture."""
import subprocess, sys, os

os.chdir(r'C:\Users\amit.rosen\AzureAIpilot')
sys.stdout.reconfigure(encoding='utf-8')

result = subprocess.run(
    [r'.venv\Scripts\python.exe', 'tests/eval_dataset.py', '--judge'],
    capture_output=False,
    encoding='utf-8',
    errors='replace',
    cwd=r'C:\Users\amit.rosen\AzureAIpilot'
)
print(f'\nEval completed with exit code: {result.returncode}')
