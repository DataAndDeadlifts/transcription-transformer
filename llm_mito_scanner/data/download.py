# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/00 data.download.ipynb.

# %% auto 0
__all__ = ['load_config', 'download_data', 'get_latest_assembly_path', 'get_genomic_genbank_path',
           'extract_accession_sequence_records', 'get_chromosome_sequence_record']

# %% ../../nbs/00 data.download.ipynb 3
from yaml import safe_load
from pathlib import Path
import typing
import subprocess
from tqdm import tqdm
import gzip
from Bio import SeqIO, SeqRecord
import pandas as pd

# %% ../../nbs/00 data.download.ipynb 5
def load_config(path: Path = Path("../config.yml")) -> dict[typing.Any, typing.Any]:
    with open(path) as f:
        return safe_load(f)

# %% ../../nbs/00 data.download.ipynb 8
def download_data(data_path: Path):
    data_raw_path = data_path / "raw"
    assemblies_path = data_raw_path / "assemblies"
    if not assemblies_path.exists():
        assemblies_path.mkdir(parents=True)
    # Get latest reference genome data
    subprocess.call([
        "rsync", "--copy-links", "--recursive", "--times", "--verbose",
        "--exclude=Annotation_comparison",
        "--exclude=*_assembly_structure",
        "--exclude=*_major_release_seqs_for_alignment_pipelines",
        "--exclude=RefSeq_historical_alignments",
        "--exclude=RefSeq_transcripts_alignments",
        "rsync://ftp.ncbi.nlm.nih.gov/genomes/refseq/vertebrate_mammalian/Homo_sapiens/reference/",
        str(assemblies_path.resolve())
    ])    

# %% ../../nbs/00 data.download.ipynb 11
def get_latest_assembly_path(
        assemblies_path: Path # Path for downloaded assemblies
        ) -> Path: # Path of the latest assembly
    "Get the latest annotation path."
    annotations = [d for d in assemblies_path.iterdir() if d.is_dir()]
    annotations_df = pd.DataFrame(annotations, columns=['path'])
    annotations_df.loc[:, 'accession'] = annotations_df.path.apply(lambda p: p.name)
    annotations_df.loc[:, 'accession_prefix'] = annotations_df.accession.apply(
        lambda acc: acc.split(".", 1)[0]
    )
    annotations_df.sort_values("accession_prefix", inplace=True, ascending=False)
    return annotations_df.iloc[0, 0]

# %% ../../nbs/00 data.download.ipynb 13
def get_genomic_genbank_path(
        assembly_path: Path # Annotation path,
        ) -> Path: # Genomic genbank path
    "Get the genomic genbank file."
    return next(assembly_path.glob("*[!from]_genomic.gbff.gz"), None)

# %% ../../nbs/00 data.download.ipynb 19
def extract_accession_sequence_records(
        genomic_genbank_path: Path, # Path to the genomic genbank file for an assembly
        assembly_path: Path, # Path to write the files to
        expected_accessions: int = 24
):
    write_path = assembly_path / "chromosomes"
    if not write_path.exists():
        write_path.mkdir()
    pbar = None
    if isinstance(expected_accessions, int):
        pbar = tqdm(total=expected_accessions, ncols=80, leave=True)
    try:
        with gzip.open(str(genomic_genbank_path.resolve()), mode='rt') as f:
            for record in SeqIO.parse(f, "genbank"):
                # Only write complete genomic molecules
                if record.id.startswith("NC_"):
                    record_write_path = write_path / f"{record.id}.gb"
                    if not record_write_path.exists():
                        SeqIO.write(record, record_write_path, "genbank")
                    if pbar is not None:
                        pbar.update(1)
    except Exception as e:
        raise e
    finally:
        if pbar is not None:
            pbar.close()

# %% ../../nbs/00 data.download.ipynb 23
def get_chromosome_sequence_record(
        chromosomes_path: str,
        refseq: str
) -> SeqRecord:
    refseq_path = chromosomes_path / f"{refseq}.gb"
    with refseq_path.open("r") as f:
        return next(SeqIO.parse(f, "genbank"), None)