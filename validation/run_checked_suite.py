"""Run the explicitly documented offline subset; omitted modules are not passes."""
from pathlib import Path
import os
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
modules=(ROOT/'validation/tested_modules.txt').read_text().splitlines()
print(f'Running the documented {len(modules)}-module subset. See excluded_modules.json for omissions.',flush=True)
print('One xhtml2pdf-specific failure-injection test is deselected; see TEST_RESULTS.md.',flush=True)
env=os.environ.copy()
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
    env.setdefault(name,'1')
raise SystemExit(subprocess.call([sys.executable,'-m','pytest','-q',*modules,'-k',
    'not test_pdf_rendering_failure_raises_instead_of_returning_a_partial_file'],cwd=ROOT/'api',env=env))
