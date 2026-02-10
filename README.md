# Demo Repository

This repository implements a typical IR experiment which can be automatically reproduced using TIRA/TIREx and the TIREx-tracker.


1. Run the reproducibility check: `./repro-check.py`
2. Run locally: `./main.py --dataset "irds:antique/test" -o ./out`
3. Try to reproduce from the output directory: `./repro.py ./out`

**Dry run**:
tira-cli code-submission --path "./" --command="./main.py -o \$outputDir -i \$inputDataset" --task lsr-benchmark --dry-run