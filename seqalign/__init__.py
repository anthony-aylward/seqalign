"""Manage sequence alignments

This module treats a "sequence alignment" as an abstraction, but mostly handles
it as a BAM file stored in memory.

Examples
--------
with SequenceAlignment(<path to input BAM or FASTQ file>) as sa:
    sa.cleans_up_bam = False
    sa.remove_supplementary_alignments()
    sa.samtools_sort(memory_limit=10)
    sa.samtools_index()
    sa.write(<path to output BAM file>)

Notes
-----
The "input_file" argument should be a string for single-end reads or for
data that is already aligned. For raw paired-end reads, it should be a tuple 
containing two strings giving the paths to the two FASTA / FASTQ files.

High-level classes
------------------
SequenceAlignment
    object representing aligned sequencing data

Low-level classes
-----------------
BWA
    wrapper for bwa
Bowtie2
    wrapper for botwie2
RemoveDuplicates
    dedupper based on samtools view

Functions
---------
samtools_fixmate
median_read_length
    determine the median length of reads in a fasta or fastq file
"""

from seqalign.seqalign import (
    SequenceAlignment, BWA, Bowtie2, RemoveDuplicates, samtools_fixmate,
    get_median_read_length, samtools_merge, merge, trim_galore
)