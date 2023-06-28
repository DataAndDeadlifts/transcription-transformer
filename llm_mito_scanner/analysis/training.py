# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/04_training-data-eda.ipynb.

# %% auto 0
__all__ = ['detect_gene_to_protein_map', 'get_training_annotation_paths', 'get_annotation', 'get_annotation_length',
           'record_annotation_length', 'get_annotation_token_count', 'record_token_count',
           'count_training_instances_with_window_size']

# %% ../../nbs/04_training-data-eda.ipynb 3
import pandas as pd
from pathlib import Path
from tqdm.auto import tqdm
from Bio import SeqIO

# %% ../../nbs/04_training-data-eda.ipynb 11
def detect_gene_to_protein_map(list_of_paths: list[Path]):
    list_of_paths_is_protein_map = [p for p in list_of_paths if p.stem == "gene_to_protein_map"]
    if len(list_of_paths_is_protein_map) == 0:
        return None
    elif len(list_of_paths_is_protein_map) > 1:
        raise ValueError("Somehow there are two gene to protein maps")
    return list_of_paths_is_protein_map[0]

# %% ../../nbs/04_training-data-eda.ipynb 23
def get_training_annotation_paths(training_data_path: Path) -> (dict, pd.DataFrame):
    """
    Search the training data path for actual annotations to use.
    """
    training_annotation_directories = pd.Series(training_data_path.glob("*"))
    training_annotation_directories.name = "annotation_path"
    training_data = training_annotation_directories.to_frame()
    training_data.loc[:, 'annotation'] = training_data.annotation_path.apply(lambda p: p.stem)
    del training_annotation_directories
    # Get all gene directories,  under the annotation directories
    training_data.loc[:, 'annotation_objects'] = training_data.annotation_path.progress_apply(
        lambda p: [p for p in list(p.glob("*")) if p.is_dir()]
    )
    # Get the path for the protein to gene map file
    training_data.loc[:, 'protein_map_file'] = training_data.annotation_path.apply(
        lambda anno_path: next(anno_path.glob("gene_to_protein_map.csv"), None)
    )
    # Get the files under the 
    training_data.loc[:, "gene_directories"] = training_data.annotation_objects.progress_apply(
        lambda anno_list: [obj for obj in anno_list if obj.is_dir()]
    )
    # Get the annotation, gene to protein map file map
    gene_to_protein_maps = training_data.set_index('annotation').protein_map_file
    gene_annotations = training_data[
        training_data.gene_directories.apply(len) > 0
    ].set_index('annotation').explode('gene_directories').drop(
        ["protein_map_file", "annotation_objects", "annotation_path"], 
        axis=1
    )
    gene_annotations.loc[:, 'annotations'] = gene_annotations.gene_directories.progress_apply(
        lambda p: list(p.glob("*.txt"))
    )
    gene_annotations.loc[:, 'gene_annotation'] = gene_annotations.annotations.progress_apply(
        lambda anno_list: next(iter([p for p in anno_list if p.stem == "gene"]), None)
    )
    gene_annotations.loc[:, 'protein_annotations'] = gene_annotations.annotations.apply(
        lambda anno_list: [p for p in anno_list if p.stem != "gene"]
    )
    gene_annotations.loc[:, 'gene'] = gene_annotations.gene_directories.apply(
        lambda p: p.stem
    )
    training_annotations = gene_annotations.set_index('gene', append=True).drop(
        [
            "annotations", 
            "gene_directories",
        ],
        axis=1
    ).explode('protein_annotations').reset_index(drop=False).rename(
        {
            "protein_annotations": "protein_annotation"
        },
        axis=1
    )
    return gene_to_protein_maps, training_annotations

# %% ../../nbs/04_training-data-eda.ipynb 27
def get_annotation(path: Path):
    with path.open("r") as f:
        return f.read().split(" ")

# %% ../../nbs/04_training-data-eda.ipynb 29
def get_annotation_length(annotation: list[str]):
    return len(annotation)

# %% ../../nbs/04_training-data-eda.ipynb 30
def record_annotation_length(annotation_label: str, annotation_path: Path, length_record: dict):
    if annotation_label in length_record:
        return
    annotation = get_annotation(annotation_path)
    annotation_length = get_annotation_length(annotation)
    length_record[annotation_label] = annotation_length

# %% ../../nbs/04_training-data-eda.ipynb 43
from collections import Counter

def get_annotation_token_count(annotation: list[str]):
    token_count = Counter(annotation)
    return token_count


def record_token_count(annotation_id: str, annotation_path: Path, token_count_record: dict):
    if annotation_id in token_count_record:
        return
    annotation = get_annotation(annotation_path)
    annotation_token_count = get_annotation_token_count(annotation)
    token_count_record[annotation_id] = annotation_token_count

# %% ../../nbs/04_training-data-eda.ipynb 62
def count_training_instances_with_window_size(annotation_size: int, window_sizes: list[int]) -> dict:
    instance_counts = {}
    for window in window_sizes:
        instance_counts[window] = math.floor(annotation_size / window)
    return instance_counts