#!/usr/bin/env python3
from pathlib import Path
from argparse import ArgumentParser
import tempfile

import tirex_tracker as tt
import pyterrier as pt
from pyterrier.measures import nDCG, MAP, RR

if not pt.started():
    pt.init()

def run_experiment(dataset: str, outdir: Path):
    # Preparation (download the dataset and construct the index)
    dataset = pt.get_dataset(dataset)
    path_to_index = Path(tempfile.gettempdir()) / "tira-repro-demo-index"
    if path_to_index.exists():
        indexref = pt.IndexRef.of(str(path_to_index.absolute()))
    else:
        indexer = pt.IterDictIndexer(
            str(path_to_index.absolute()), text_attrs=["text"])
        indexref = indexer.index(dataset.get_corpus_iter())
    index = pt.IndexFactory.of(indexref)

    # Define the pipeline
    pipeline = pt.terrier.Retriever(index, wmodel="BM25") % 100

    # Run the experiment
    # metadata = {"data": {"test collection": {"name": "ANTIQUE", "source": "https://ciir.cs.umass.edu/downloads/Antique/",
    #                                         "qrels": "https://ciir.cs.umass.edu/downloads/Antique/antique-test.qrel", "topics": "https://ciir.cs.umass.edu/downloads/Antique/antique-collection.txt", "ir_datasets": "https://ir-datasets.com/antique#antique/test"}}}
    # tt.register_metadata(metadata)
    with tt.tracking(export_file_path=str(outdir/"irmetadata.yaml")):
        results = pipeline(dataset.get_topics())

    pt.io.write_results(results, str(outdir/"run.txt"))

    print(pt.Experiment([pipeline], dataset.get_topics(
    ), dataset.get_qrels(), eval_metrics=[nDCG@10, MAP(rel=3), RR(rel=3)]))


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--dataset", required=True, type=str)
    parser.add_argument("-o", "--output-directory", required=True, type=Path)
    args = parser.parse_args()

    run_experiment(args.dataset, args.output_directory)
