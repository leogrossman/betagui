"""Configurations for the MLS storage ring."""

from importlib import resources
import at
from reflat_tools.paths import DefaultPath
from reflat_tools.configuration import set_configuration


# Set the default path for where to find data
DEFAULT_PATH = DefaultPath(__package__)

# ----------------------------------------------------------------------------
# Injection
# Crude first guess as starting point for LOCO fit
# ----------------------------------------------------------------------------

def injection(ring) -> at.Lattice:
    filename = "mls_storage_ring_injection.csv"
    ring = set_configuration(ring, DEFAULT_PATH.set_filepath(filename))

    ring.energy = 105e6

    ring.set_value_refpts(ring.cavpts,'Voltage',72e3)

    return ring

# ----------------------------------------------------------------------------
# Low alpha
# Settings from old MADX reference file 
# ----------------------------------------------------------------------------

def low_alpha(ring) -> at.Lattice:
    filename = "mls_storage_ring_low_alpha.csv"
    ring = set_configuration(ring, DEFAULT_PATH.set_filepath(filename))
    
    return ring

# ----------------------------------------------------------------------------
# Low emittance
# Settings from old MADX reference file 
# ----------------------------------------------------------------------------

def low_emittance(ring) -> at.Lattice:
    filename = "mls_storage_ring_low_emittance.csv"
    ring = set_configuration(ring, DEFAULT_PATH.set_filepath(filename))
    
    return ring

# ----------------------------------------------------------------------------
# SSMB
# Settings from Arnold's elegant file  
# ----------------------------------------------------------------------------

def ssmb(ring) -> at.Lattice:
    filename = "mls_storage_ring_ssmb.csv"
    ring = set_configuration(ring, DEFAULT_PATH.set_filepath(filename))
    
    return ring
