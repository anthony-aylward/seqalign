"""Easy management of sequence alignment data

A mini-module for managing sequence alignment data. The language of this module
treats a "sequence alignment" as an abstraction, but mostly handles it as a BAM 
file stored in memory.

Examples
--------
with SequenceAlignment(<path to input bam or fastq file>) as sa:
    sa.cleans_up_bam = False
    sa.remove_supplementary_alignments()
    sa.samtools_sort(memory_limit=10)
    sa.samtools_index()
    sa.write(<path to output BAM file>)

Notes
-----
The "input_file" argument should be a string for single-end reads or for
data that is already aligned. For raw paired-end reads, it should be a tuple 
containing two strings giving the paths to the two fasta / fastq files.

High-level classes
------------------
SequenceAlignment
    object representing aligned sequencing data

Low-level classes
-----------------
BWA
    commands for running bwa

Functions
---------
file_format_from_extension
    infer the format of a sequencing data file from its extension
median_read_length
    determine the median length of reads in a fasta or fastq file
"""