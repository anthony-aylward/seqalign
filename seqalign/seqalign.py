#!/usr/bin/env python3
#===============================================================================
# seqalign.py
#===============================================================================

# Imports ======================================================================

import gzip
import itertools
import math
import os
import os.path
import pyhg19
import subprocess
import tempfifo
import tempfile

from Bio import SeqIO
from glob import glob




# Classes ======================================================================

class SequenceAlignment():
    """A representation of aligned sequencing data
    
    Attributes
    ----------
    bam : bytes
        Aligned sequencing data in BAM format
    index : bytes
        BAI index file generated by samtools index
    mapping_quality : int
        Minimum MAPQ score for reads in this alignment
    bam_file_path : str
        File path used the last time the BAM was written to disk
    cleans_up_bam : bool
        When True, __exit__() will remove the last BAM file written to disk
    is_sorted : bool
        Defaults to False, becomes True after samtools_sort() is run
    aligner : obj
        A callable object representing the aligner used for sequence alignment
    dedupper : obj
        A callable object representing the algorithm used for removing
        duplicates
    processes : int
        Maximum number of processes available for method calls
    log : file object
        File object to which logging information will be written
    """
  
    def __init__(
        self,
        input_file,
        mapping_quality=10,
        aligner=None,
        dedupper=None,
        processes=1,
        log=None,
        temp_dir=None
    ):
        """Set the parameters for the alignment
        
        Parameters
        ----------
        input_file : bytes, tuple, list, str
            Sequencing data. Bytes objects are assumed to be BAM files in
            memory. Strings are assumed to be paths to sequencing data on
            disk. Tuples or lists are assumed to be pairs of strings indicating
            paired-end read files.
        mapping_quality : int
            Minimum MAPQ score for reads in this alignmentaligner : obj
        alignment : obj
            A callable object representing the aligner used for sequence
            alignment
        dedupper : obj
            A callable object representing the algorithm used for removing
            duplicates
        processes : int
            Maximum number of processes available for method calls
        log : file object
            File object to which logging information will be written
        temp_dir
            directory for temporary files
        """
        
        self.index = None
        self.mapping_quality = int(mapping_quality)
        self.bam_file_path = None
        self.cleans_up_bam = False
        self.is_sorted = False
        self.aligner = aligner
        self.dedupper = dedupper
        self.processes = int(processes)
        self.log = log
        self.temp_dir = temp_dir
        self.bam = self.parse_input(input_file)
    
    def __enter__(self):
        """When an instance of this class is used as a context manager, it is
        assumed that a BAM file written to disk should be removed after exiting
        context.
        """
        
        self.cleans_up_bam = True
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        """Clean up a BAM file on disk"""
        
        if self.cleans_up_bam:
            self.clean_up(self.bam_file_path)
            self.clean_up('{}.bai'.format(self.bam_file_path))
        return False
    
    def __repr__(self):
        """Show some of the alignment parameters"""
        
        return '\n'.join(
            (
                'SequenceAlignment(',
                f'    mapping_quality   : {self.mapping_quality}',
                f'    processes             : {self.processes}',
                f'    cleans_up_bam         : {self.cleans_up_bam}',
                ')'
            )
        )
    
    def __add__(self, sequence_alignment):
        """Merge this SequenceAlignment with another one
        
        If the ``+`` operator is used, the resulting alignment will use the
        max of the two minimum MAPQ scores. If the ``|`` operator is used, the
        resulting alignment will use the min of the two minimum MAPQ scores.
        
        Parameters
        ----------
        sequence_alignment : SequenceAlignment
            Another SequenceAlignment object
        
        Returns
        -------
        SequenceAlignment
            A SequenceAlignment object representing data generated by samtools
            merge
        """
        
        return merge(
            self,
            sequence_alignment,
            mapping_quality=max(
                self.mapping_quality,
                sequence_alignment.mapping_quality
            ),
            processes=min(self.processes, sequence_alignment.processes),
            temp_dir=self.temp_dir
        )
    
    def __or__(self, sequence_alignment):
        """Merge this SequenceAlignment with another one
        
        If the ``+`` operator is used, the resulting alignment will use the
        max of the two minimum MAPQ scores. If the ``|`` operator is used, the
        resulting alignment will use the min of the two minimum MAPQ scores.
        
        Parameters
        ----------
        sequence_alignment : SequenceAlignment
            Another SequenceAlignment object
        
        Returns
        -------
        SequenceAlignment
            A SequenceAlignment object representing data generated by samtools
            merge
        """
        
        return merge(
            self,
            sequence_alignment,
            mapping_quality=min(
                self.mapping_quality,
                sequence_alignment.mapping_quality
            ),
            processes=min(self.processes, sequence_alignment.processes),
            temp_dir=self.temp_dir
        )
    
    def parse_input(self, input_file):
        """Parse the input file
        
        Aligns sequencing data if necessary, and finally assigns an appropriate
        bytes object to the bam attribute
        
        Parameters
        ----------
        input_file : bytes, tuple, list, str
            Sequencing data. Bytes objects are assumed to be BAM files in
            memory. Strings are assumed to be paths to sequencing data on
            disk. Tuples or lists are assumed to be pairs of strings indicating
            paired-end read files.
        
        Returns
        -------
        bytes
            A BAM File in memory
        """
        
        if not isinstance(input_file, (bytes, tuple, list, str)):
            raise TypeError('input_file must be bytes, tuple, list, or str')
        elif isinstance(input_file, bytes):
            return input_file
        elif isinstance(input_file, (tuple, list)):
            if len(input_file) != 2:
                raise ValueError(
                    'If input_file_path is a tuple, it must have length 2'
                )
            self.raw_reads_path = input_file
            return self.align_reads()
        elif isinstance(input_file, str):
            format = file_format_from_extension(input_file)
            if format in {'fasta', 'fastq'}:
                self.raw_reads_path = input_file
                return self.align_reads()
            elif format in {'sam', 'bam'}:
                with subprocess.Popen(
                    (
                        'samtools', 'view',
                        '-bhq', str(self.mapping_quality),
                        '-@', str(self.processes),
                        input_file
                    ),
                    stdout=subprocess.PIPE,
                    stderr=self.log
                ) as samtools_view:
                    return samtools_view.communicate()[0]
    
    def align_reads(self):
        """Align raw reads using the provided aligner
        
        The default aligner is BWA
        
        Returns
        -------
        bytes
            A BAM File in memory
        """
        
        if not self.aligner:
            self.aligner = BWA()
        return self.aligner(self, temp_dir=self.temp_dir)
    
    def samtools_view(
        self,
        *options,
        remove_unpaired=False,
        remove_improperly_paired=False,
        remove_unmapped=False,
        remove_mate_unmapped=False,
        remove_not_primary=False,
        remove_fails_quality_check=False,
        remove_duplicate=False,
        remove_supplementary=False,
        mapping_quality=None
    ):
        """Apply a filter to the BAM file with samtools view

        Parameters
        ----------
        options : tuple
            tuple containing the options as to be passed to subprocess.Popen
        """
        
        with subprocess.Popen(
            (
                (
                    'samtools', 'view', '-bh', '-@', str(self.processes - 1),
                    '-q', str(
                        self.mapping_quality
                        if mapping_quality is None
                        else mapping_quality
                    )
                )
                + tuple(options)
                + remove_unpaired * ('-f', '1')
                + remove_improperly_paired * ('-f', '2')
                + remove_unmapped * ('-F', '4')
                + remove_mate_unmapped * ('-F', '8')
                + remove_not_primary * ('-F', '256')
                + remove_fails_quality_check * ('-F', '512')
                + remove_duplicate * ('-F', '1024')
                + remove_supplementary * ('-F', '2048')
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log
        ) as samtools_view:
            bam, _ = samtools_view.communicate(input=self.bam)
        self.bam = bam
    
    def remove_unpaired_reads(self):
        """Remove unpaired (or improperly paired) reads from the BAM data using
        samtools view
        """
        
        self.samtools_view(remove_unpaired=True)
    
    def remove_supplementary_alignments(self):
        """Remove supplementary alignments from the BAM data using samtools
        view
        """
        
        self.samtools_view(remove_supplementary=True)
    
    def apply_quality_filter(self):
        """Apply a quality filter to the BAM data using samtools view, with 
        flags: -F 1804 -q {mapping_quality}
        """
        
        self.samtools_view('-F', '1804', '-q', str(self.mapping_quality))
    
    def percent_mitochondrial(self):
        if not self.index:
            raise RuntimeError(
                'use SequenceAlignment.samtools_index() before using '
                'SequenceAlignment.percent_mitochondrial()'
            )
        with tempfile.NamedTemporaryFile(dir=self.temp_dir) as temp_bam:
            temp_bam.write(self.bam)
            with open('{}.bai'.format(temp_bam.name), 'wb') as f:
                f.write(self.index)
            with subprocess.Popen(
                ('samtools', 'view', '-c', temp_bam.name),
                stdout=subprocess.PIPE,
                stderr=self.log
            ) as samtools_view:
                total = int(samtools_view.communicate()[0].decode())
            with subprocess.Popen(
                ('samtools', 'view', '-c', temp_bam.name, 'chrM'),
                stdout=subprocess.PIPE,
                stderr=self.log
            ) as samtools_view:
                mitochondrial = int(samtools_view.communicate()[0].decode())
            os.remove('{}.bai'.format(temp_bam.name))
            return mitochondrial / total

    def restrict_chromosomes(self, *chromosomes):
        """Restrict the BAM data to reads on certain chromosomes
        
        Parameters
        ----------
        *chromosomes
            the chromosomes to include
        """
        
        if not self.index:
            raise RuntimeError(
                'use SequenceAlignment.samtools_index() before using '
                'SequenceAlignment.restrict_chromosomes()'
            )
        with tempfile.NamedTemporaryFile(dir=self.temp_dir) as temp_bam:
            temp_bam.write(self.bam)
            with open('{}.bai'.format(temp_bam.name), 'wb') as f:
                f.write(self.index)
            self.samtools_view(
                temp_bam.name,
                *(f'chr{c}'.replace('chrchr', 'chr') for c in chromosomes)
            )
            os.remove('{}.bai'.format(temp_bam.name))
    
    def samtools_index(self):
        """Index the BAM data
        """
        
        if not self.is_sorted:
            raise Exception('BAM must be sorted before it can be indexed')
        with tempfifo.NamedTemporaryFIFO(dir=self.temp_dir) as (
            bam_pipe
        ), tempfifo.NamedTemporaryFIFO(dir=self.temp_dir) as (
            index_pipe
        ):
            with subprocess.Popen(
                (
                    'sh', '-c',
                    'cat {0} & samtools index {1} {0} & cat > {1}'.format(
                        index_pipe.name,
                        bam_pipe.name
                    )
                ),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self.log
            ) as samtools_index:
                self.index, _ = samtools_index.communicate(input=self.bam)
    
    def samtools_sort(self, memory_limit=5):
        """Sort the BAM data using samtools"""
        
        if memory_limit < 5:
            raise MemoryLimitError('Please provide at least 5 GB of memory')
        with subprocess.Popen(
            (
                'samtools', 'sort',
                '-T', str(self.temp_dir or tempfile.gettempdir()),
                '-m', '{}M'.format(int(1024 / self.processes * memory_limit)),
                '-@', str(self.processes - 1)
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log
        ) as samtools_sort:
            bam, _ = samtools_sort.communicate(input=self.bam)
        self.bam = bam
        self.is_sorted=True
    
    def percent_blacklisted(self, blacklist_path):
        with subprocess.Popen(
            ('samtools', 'view', '-c'),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log
        ) as samtools_view:
            total = int(samtools_view.communicate(input=self.bam)[0].decode())
        with subprocess.Popen(
            ('bedtools', 'intersect', '-abam', 'stdin', '-b', blacklist_path),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log
        ) as bedtools_intersect:
            blacklisted_bam, _ = bedtools_intersect.communicate(input=self.bam)
        with subprocess.Popen(
            ('samtools', 'view', '-c'),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log
        ) as samtools_view:
            blacklisted = int(
                samtools_view.communicate(input=blacklisted_bam)[0].decode()
            )
        return blacklisted / total

    def remove_blacklisted_reads(self, blacklist_path):
        """Remove reads from regions in a provided BED file using bedtools
        
        Parameters
        ----------
        blacklist_path : str
            Path to a BED file on disk
        """
        
        with subprocess.Popen(
            (
                'bedtools', 'intersect',
                '-abam', 'stdin',
                '-b', blacklist_path,
                '-v'
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log
        ) as bedtools_intersect:
            bam, _ = bedtools_intersect.communicate(input=self.bam)
        self.bam = bam
    
    def remove_duplicates(self, dedupper=None):
        """Remove duplicates from the BAM data using the provided dedupper"""
        
        if not (dedupper or self.dedupper):
            raise Exception(
                "Indicate a dedupper if you're going to remove duplicates"
            )
        else:
            dedupper = dedupper if dedupper else self.dedupper
            self.bam = dedupper(self.bam, log=self.log)
    
    def samtools_mpileup(self, positions, reference_genome=pyhg19.PATH):
        """Generate a pileup from the BAM data using samtools mpileup
        
        Parameters
        ----------
        positions : str
            Path to a variant positions file on disk
        reference_genome : 
            Path to a reference genome on disk
        
        Returns
        -------
        bytes
            A pileup file generated by samtools mpileup
        """
        
        with subprocess.Popen(
            (
                'samtools', 'mpileup',
                '-f', reference_genome,
                '-l', positions,
                '-'
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log
        ) as samtools_mpileup:
            return samtools_mpileup.communicate(self.bam)[0]
    
    def samtools_fixmate(self):
        """Apply samtools fixmate to the alignment"""
        
        self.bam = samtools_fixmate(self.bam, log=self.log)
    
    def write(self, bam_file_path):
        """Write a BAM file to disk, along with an index if one is present
        
        Parameters
        ----------
        bam_file_path : str
            Path where the BAM file will be written
        """
        
        with open(bam_file_path, 'wb') as f:
            f.write(self.bam)
        self.bam_file_path = bam_file_path
        if self.index:
            with open('{}.bai'.format(bam_file_path), 'wb') as f:
                f.write(self.index)
    
    def clean_up(self, path):
        """Remove a file
        
        Parameters
        ----------
        path
            path to file that will be removed
        """
        
        if (os.path.isfile(path) if path else False):
            os.remove(path)


class BWA():
    """A class with methods for calling BWA
    
    Notes
    -----
    BWA defaults:
        trim_qual:     0
        seed_len:      inf
        max_seed_diff: 2
    
    AQUAS (Kundaje lab) defaults for ChIP-seq:
        trim_qual:     5
        seed_len:      32
        max_seed_diff: 2
    
    Gaulton lab ChIP-seq pipeline settings:
        trim_qual:     15
        seed_len:      inf
        max_seed_diff: 2
    
    Attributes
    ----------
    reference_genome_path : str
        Path to a reference genome on disk
    trim_qual : int
        MAPQ score for read trimming
    seed_len : int
        Seed length [inf]
    max_seed_diff : int
        Maximum mismatches in seed before a read is dropped [2]
    max_reads_for_length_check : int
        Maximum number of reads to use for read length checking [1e6]
    algorithm : str
        If set, force use of either the aln or the mem algorithm
    algorithm_switch_bp : int
        Read length at which the algorithm will automatically switch from aln
        to mem [70]
    """
    
    def __init__(
        self,
        reference_genome_path=pyhg19.PATH,
        trim_qual=0,
        seed_len='inf',
        max_seed_diff=2,
        max_reads_for_length_check=int(1e6),
        algorithm=None,
        algorithm_switch_bp=70
    ):
        """Set the parameters for sequence alignment with BWA
        
        Parameters
        ----------
        reference_genome_path : str
            Path to a reference genome on disk
        trim_qual : int
            MAPQ score for read trimming
        seed_len : int
            Seed length [inf]
        max_seed_diff : int
            Maximum mismatches in seed before a read is dropped [2]
        max_reads_for_length_check : int
            Maximum number of reads to use for read length checking [1e6]
        """
        
        self.reference_genome_path = reference_genome_path
        self.trim_qual = int(trim_qual) if trim_qual else 0
        self.seed_len = seed_len
        self.max_seed_diff = max_seed_diff
        self.max_reads_for_length_check = max_reads_for_length_check
        self.algorithm = algorithm
        self.algorithm_switch_bp = algorithm_switch_bp
    
    def __repr__(self):
        return 'BWA()'
    
    def __call__(self, sequence_alignment, temp_dir=None):
        """Perform sequence alignment using an appropriate algorithm
        
        First, read lengths are checked to determine the appropriate algorithm,
        then the alignment is carried out.
        
        Parameters
        ----------
        sequence_alignment : SequenceAlignment
            a SequenceAlignemnt object
        temp_dir : str
            directory for temporary files
        
        Returns
        -------
        bytes
            A BAM file in memory
        """
        
        if self.algorithm == 'aln':
            return self.bwa_aln(sequence_alignment, temp_dir=temp_dir)
        if self.algorithm == 'mem':
            return self.bwa_mem(sequence_alignment)
        
        median_read_length = get_median_read_length(
            sequence_alignment.raw_reads_path,
            self.max_reads_for_length_check
        )
        if median_read_length <= self.algorithm_switch_bp:
            return self.bwa_aln(sequence_alignment, temp_dir=temp_dir)
        elif median_read_length > self.algorithm_switch_bp:
            return self.bwa_mem(sequence_alignment)
    
    def bwa_aln(self, sequence_alignment, temp_dir=None):
        """Perform sequence alignment using the bwa aln algorithm
        
        Single-end and paired end reads are handled appropriately based on the
        type of the SequenceAlignment's raw reads path
        
        Parameters
        ----------
        sequence_alignment : SequenceAlignment
            a SequenceAlignemnt object
        temp_dir : str
            directory for temporary files
        
        Returns
        -------
        bytes
            A BAM file
        """
        
        if not isinstance(sequence_alignment.raw_reads_path, str):
            with tempfifo.NamedTemporaryFIFO(dir=temp_dir) as (
                sai_pipe_0
            ), tempfifo.NamedTemporaryFIFO(dir=temp_dir) as (
                sai_pipe_1
            ):
                with subprocess.Popen(
                    (
                        'sh', '-c',
                        (
                            'bwa sampe {0} {1} {2} {3} {4} & '
                            'bwa aln -t {5} -q {6} -l {7} -k {8} {0} {3} > '
                            '{1} & '
                            'bwa aln -t {5} -q {6} -l {7} -k {8} {0} {4} > '
                            '{2} & '
                        )
                        .format(
                            self.reference_genome_path,
                            sai_pipe_0.name,
                            sai_pipe_1.name,
                            sequence_alignment.raw_reads_path[0],
                            sequence_alignment.raw_reads_path[1],
                            math.floor(sequence_alignment.processes / 2),
                            self.trim_qual,
                            self.seed_len,
                            self.max_seed_diff
                        )
                    ),
                    stdout=subprocess.PIPE,
                    stderr=sequence_alignment.log
                ) as bwa_aln_sampe:
                    with subprocess.Popen(
                        (
                            'samtools', 'view',
                            '-Sbq', str(sequence_alignment.mapping_quality),
                            '-@', str(sequence_alignment.processes)
                        ),
                        stdin=bwa_aln_sampe.stdout,
                        stdout=subprocess.PIPE,
                        stderr=sequence_alignment.log
                    ) as samtools_view:
                        return samtools_view.communicate()[0]
        else:
            with tempfifo.NamedTemporaryFIFO(dir=temp_dir) as sai_pipe:
                with subprocess.Popen(
                    (
                        'sh', '-c',
                        (
                            'bwa samse {0} {1} {2} & '
                            'bwa aln -t {3} -q {4} -l {5} -k {6} {0} {2} > {1}; '
                        )
                        .format(
                            self.reference_genome_path,
                            sai_pipe.name,
                            sequence_alignment.raw_reads_path,
                            sequence_alignment.processes,
                            self.trim_qual,
                            self.seed_len,
                            self.max_seed_diff
                        )
                    ),
                    stdout=subprocess.PIPE,
                    stderr=sequence_alignment.log
                ) as bwa_aln_samse:
                    with subprocess.Popen(
                            (
                                'samtools', 'view',
                                '-bhq', str(
                                    sequence_alignment.mapping_quality
                                ),
                                '-@', str(sequence_alignment.processes)
                            ),
                            stdin=bwa_aln_samse.stdout,
                            stdout=subprocess.PIPE,
                            stderr=sequence_alignment.log
                        ) as samtools_view:
                            return samtools_view.communicate()[0]
    
    def bwa_mem(self, sequence_alignment):
        """Perform sequence alignment using the bwa mem algorithm
        
        Parameters
        ----------
        sequence_alignment : SequenceAlignment
            a SequenceAlignemnt object
        
        Returns
        -------
        bytes
            A BAM file
        """
        
        with subprocess.Popen(
            (
                'bwa', 'mem', '-M', '-t', str(sequence_alignment.processes),
                self.reference_genome_path
            )
            + (
                tuple(sequence_alignment.raw_reads_path)
                if not isinstance(sequence_alignment.raw_reads_path, str)
                else (sequence_alignment.raw_reads_path,)
            ),
            stdout=subprocess.PIPE,
            stderr=sequence_alignment.log
        ) as bwa_mem:
            with subprocess.Popen(
                (
                    'samtools', 'view',
                    '-bhq', str(sequence_alignment.mapping_quality),
                    '-@', str(sequence_alignment.processes)
                ),
                stdin=bwa_mem.stdout,
                stdout=subprocess.PIPE,
                stderr=sequence_alignment.log
            ) as samtools_view:
                return samtools_view.communicate()[0]


class Bowtie2():
    """A class with methods for calling Bowtie2

    Parameters
    ----------
    index
        prefix for bowtie2 index
    
    Attributes
    ----------
    index
        prefix for bowtie2 index
    """

    def __init__(self, index=pyhg19.BOWTIE2_INDEX):
        self.index = index

    def __repr__(self):
        return f'Bowtie2(index={self.index})'

    def __call__(self, sequence_alignment):
        with subprocess.Popen(
            (
                'bowtie2',
                '-x', self.index,
                '--threads', str(sequence_alignment.processes),
                '--maxins', '2000'
            )
            + (
                (
                    '-1', sequence_alignment.raw_reads_path[0],
                    '-2', sequence_alignment.raw_reads_path[1]
                )
                if not isinstance(sequence_alignment.raw_reads_path, str)
                else ('-U', sequence_alignment.raw_reads_path)
            ),
            stdout=subprocess.PIPE,
            stderr=sequence_alignment.log
        ) as bowtie2:
            with subprocess.Popen(
                (
                    'samtools', 'view',
                    '-bhq', str(sequence_alignment.mapping_quality),
                    '-@', str(sequence_alignment.processes)
                ),
                stdin=bowtie2.stdout,
                stdout=subprocess.PIPE,
                stderr=sequence_alignment.log
            ) as samtools_view:
                return samtools_view.communicate()[0]


class STAR():
    pass


class RemoveDuplicates():
    """Remove duplicates with samtools view
    
    Parameters
    ----------
    processes
        number of processes to use

    Attributes
    ----------
    processes
        number of processes to use
    """
    
    def __init__(self, processes=1):
        self.processes = processes
    
    def __call__(self, bam, log=None):
        with subprocess.Popen(
            (
              'samtools', 'view',
              '-bh',
              '-F', '0x400',
              '-@', str(self.processes)
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log if log else os.devnull
        ) as samtools_view:
            return samtools_view.communicate()[0]




# Exceptions ===================================================================

class Error(Exception):
   """Base class for other exceptions"""
   
   pass


class FileExtensionError(Error):
    """File extension error"""
    
    pass


class MemoryLimitError(Error):
    """Memory limit error"""
    
    pass


class MissingInputError(Error):
    """Missing input error"""
    
    pass




# Functions ====================================================================

def samtools_fixmate(bam: bytes, log=None):
    """Apply samtools fixmate to a BAM file (bytes object)

    Parameters
    ----------
    bam : bytes
        bytes object representing a BAM file
    
    Returns
    -------
    bytes
        BAM file with mates fixed
    """

    with subprocess.Popen(
        ('samtools', 'fixmate', '-r', '-', '-'),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log,
    ) as samtools_fixmate:
        return samtools_fixmate.communicate(bam)[0]

def file_format_from_extension(file_path):
    """Infer the format of a sequencing data file from its extension
    
    Parameters
    ----------
    file_path : str
        Path to a sequencing data file
    
    Returns
    -------
    str
        one of ``fasta``, ``fastq``, ``sam``, ``bam``
    """
    
    if (file_path.split('.')[-1] in {'fasta', 'fa'}) or (
        file_path.split('.')[-1] == 'gz' and (
            file_path.split('.')[-2] in {'fasta', 'fa'}
        )
    ):
        format = 'fasta'
    elif (file_path.split('.')[-1] in {'fastq', 'fq', 'fq1', 'fq2'}) or (
        file_path.split('.')[-1] == 'gz' and (
            file_path.split('.')[-2] in {'fastq', 'fq', 'fq1', 'fq2'}
        )
    ):
        format = 'fastq'
    elif file_path.split('.')[-1] in {'sam', 'bam'}:
        format = file_path.split('.')[-1]
    else:
        raise FileExtensionError(
            f'Could not parse file extension of {os.path.basename(file_path)}'
        )
    return format


def get_median_read_length(raw_reads_paths, number_of_reads):
    """Return the median read length of a FASTA or FASTQ file
    
    Parameters
    ----------
    raw_reads_paths : str, list, tuple
        Path to raw reads file (or paths if paired-end)
    number_of_reads : int
        Maximum number of reads to read in before determining median read length
    
    Returns
    -------
    int or float
        The median read length
    """
    
    histogram = {}
    if not isinstance(raw_reads_paths, str):
        formats = tuple(
            file_format_from_extension(raw_reads_paths[i]) for i in range(2)
        )
    else:
        formats = (file_format_from_extension(raw_reads_paths),)
        raw_reads_paths = (raw_reads_paths,)
    for raw_reads_path, format in zip(raw_reads_paths, formats):
        with (
            gzip.open(raw_reads_path, 'rt')
            if raw_reads_path[-3:] == '.gz'
            else open(raw_reads_path, 'r')
        ) as raw_reads:
            for record in itertools.islice(
                SeqIO.parse(raw_reads, format),
                number_of_reads
            ):
                try:
                    histogram[len(record.seq)] += 1
                except KeyError:
                    histogram[len(record.seq)] = 1
        if not histogram:
            raise Exception('No reads in input file')
        read_lengths = tuple(
            length for length, count in sorted(histogram.items())
        )
        total_reads = sum(count for length, count in histogram.items())
        cumulative_count = 0
        for length, count in sorted(histogram.items()):
            cumulative_count += count
            if cumulative_count > total_reads / 2:
                median = length
                break
            elif cumulative_count == total_reads / 2:
                read_lengths = tuple(
                    length for length, count in sorted(histogram.items())
                )
                next_length = read_lengths[read_lengths.index(length) + 1]
                median = (length + next_length) / 2
                break
    return median


def samtools_merge(*bams, temp_dir=None):
    """Merge BAM files using samtools merge
    
    Parameters
    ----------
    *bams
        Variable number of paths to BAM files on disk or BAM files as bytes
        objects (the two can be mixed)
    temp_dir
        directory for tempoarary files
    
    Returns
    -------
    bytes
        A BAM file in memory
    """
    
    bam_file_paths = []
    temp_files = []
    for bam in bams:
        if isinstance(bam, str):
            bam_file_paths.append(bam)
        elif isinstance(bam, bytes):
            temp = tempfile.NamedTemporaryFile(dir=temp_dir)
            temp.write(bam)
            temp_files.append(temp)
            bam_file_paths.append(temp.name)
    with subprocess.Popen(
        ['samtools', 'merge', '-'] + bam_file_paths,
        stdout=subprocess.PIPE
    ) as samtools_merge:
        bam, _ = samtools_merge.communicate()
    for temp in temp_files:
        temp.close()
    return bam


def to_bam(alignment):
    """Flatten an alignment to a BAM file in memory or on disk
    
    Parameters
    ----------
    alignment
        A string containing the path to a BAM file on disk, a bytes object
        containing a BAM file in memory, or a SequenceAlignment object
    
    Returns
    -------
    str or bytes
        Path to a BAM file on disk (str), or a BAM file in memory (bytes)
    """
    
    if isinstance(alignment, (bytes, str)):
        return alignment
    elif isinstance(alignment, SequenceAlignment):
        return alignment.bam

def merge(
    *sequence_alignments,
    mapping_quality=10,
    aligner=None,
    dedupper=None,
    processes=1,
    log=None,
    temp_dir=None
):
    """Merge SequenceAlignment objects
    
    Produces a new SequenceAlignment object with a merged bam attribute and
    other parameters as provided
    
    Parameters
    ----------
    *sequence_alignments
        One or more SequenceAlignment objects
    mapping_quality : int
        Minimum MAPQ score for reads in this alignmentaligner : obj
    alignment : obj
        A callable object representing the aligner used for sequence
        alignment
    dedupper : obj
        A callable object representing the algorithm used for removing
        duplicates
    processes : int
        Maximum number of processes available for method calls
    log : file object
        File object to which logging information will be written
    temp_dir
        directory for tempoarary files
    
    Returns
    -------
    SequenceAlignment
        A new SequenceAlignment object representing merged data
    """
    
    return SequenceAlignment(
        samtools_merge(
            *(to_bam(sa) for sa in sequence_alignments),
            temp_dir=temp_dir
        ),
        mapping_quality=mapping_quality,
        processes=processes,
        aligner=aligner,
        dedupper=dedupper,
        log=log,
        temp_dir=temp_dir
    )


def trim_galore(reads1, reads2, output):
    """trim reads for adapter sequences with trim galore
    
    Parameters
    ----------
    reads1 : str
        path to paired-end sequencing data file
    reads2 : str
        path to paired-end sequencing data file
    output : str
        directory for output files

    Returns
    -------
    tuple
        tuple of two strings giving paths to trimmed sequencing data files
    """

    with open(os.devnull, 'w') as f:
        subprocess.call(
            (
                'trim_galore',
                '--fastqc',
                '-q', '10',
                '-o', output,
                '--paired',
                '--gzip',
                reads1,
                reads2
            ),
            stderr=f,
            stdout=f
        )
    return tuple(glob(os.path.join(output, '*.fq.gz')))