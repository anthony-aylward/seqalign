# seqalign

Manage sequence alignments

## Installation

```sh
pip3 install seqalign
```
or
```sh
pip3 install --user seqalign
```

## Examples

```python
with SequenceAlignment(<path to input BAM or FASTQ file>) as sa:
    sa.cleans_up_bam = False
    sa.remove_supplementary_alignments()
    sa.samtools_sort(memory_limit=10)
    sa.samtools_index()
    sa.write(<path to output BAM file>)
```

## Notes

The `input_file` argument to `SequenceAlignment()` should be a string for
single-end reads or for data that is already aligned. For raw paired-end reads,
it should be a tuple containing two strings giving the paths to the two
FASTA / FASTQ files.
