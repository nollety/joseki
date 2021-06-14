"""Module to read atmospheric profiles distributed with Reference Forward Model.

Reference Forward Model (RFM) website: http://eodg.atm.ox.ac.uk/RFM/.
"""
import importlib.resources as pkg_resources
from datetime import datetime
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import numpy as np
import requests
import xarray as xr
from scipy.constants import physical_constants

from .data import rfm
from joseki import ureg
from joseki import util

SOURCE = "unknown"

REFERENCE = "unknown"

DESCRIPTION = {
    "win": "MIPAS (2001) polar winter",
    "sum": "MIPAS (2001) polar summer",
    "day": "MIPAS (2001) mid-latitude daytime",
    "ngt": "MIPAS (2001) mid-latitude nighttime",
    "equ": "MIPAS (2001) equatorial",
    "day_imk": "MIPAS (1998) mid-latitude daytime",
    "ngt_imk": "MIPAS (1998) mid-latitude nighttime",
    "sum_imk": "MIPAS (1998) polar summer",
    "win_imk": "MIPAS (1998) polar winter",
    "mls": "AFGL (1986) Mid-latitude summer",
    "mlw": "AFGL (1986) Mid-latitude winter",
    "sas": "AFGL (1986) Sub-arctic summer",
    "saw": "AFGL (1986) Sub-arctic winter",
    "std": "AFGL (1986) U.S. Standard",
    "tro": "AFGL (1986) Tropical",
}

# Boltzmann constant
K = ureg.Quantity(*physical_constants["Boltzmann constant"][:2])


def _parse_units(s: str) -> str:
    """Parse units."""
    if s.startswith("[") and s.endswith("]"):
        units = s[1:-1]
        if units == "mb":
            return "millibar"
        else:
            return units
    else:
        raise ValueError(f"Cannot parse units '{s}'")


def _parse_var_name(n: str) -> str:
    """Parse variable name."""
    translate = {"HGT": "z_level", "PRE": "p", "TEM": "t"}
    if n in translate.keys():
        return translate[n]
    else:
        return util.to_chemical_formula(n)


def _parse_var_line(s: str) -> Tuple[str, str]:
    """Parse a line with the declaration of a variable and its units."""
    parts = s[1:].strip().split()
    if len(parts) == 2:
        var_name, units_s = parts
    elif len(parts) == 3:
        var_name, _, units_s = parts
    else:
        raise ValueError(f"Invalid line format: {s}")
    var = _parse_var_name(var_name)
    units = _parse_units(units_s)
    return var, units


def _parse_values_line(s: str) -> List[str]:
    """Parse a line with numeric values."""
    if "," in s:  # delimiter is comma and whitespace combined
        s_strip = s.strip()
        if s_strip[-1] == ",":
            s_strip = s_strip[:-1]
        return [x.strip() for x in s_strip.split(",")]
    else:  # delimiter is whitespace
        return s.split()


def _parse_content(lines: List[str]) -> Dict[str, ureg.Quantity]:
    """Parse lines."""
    iterator = iter(lines)
    line = next(iterator)

    quantities: Dict[str, ureg.Quantity] = {}

    def _add_to_quantities(quantity: ureg.Quantity, name: str) -> None:
        if quantity.units == "ppmv":
            quantities[name] = quantity.to("dimensionless")
        else:
            quantities[name] = quantity

    var: str = ""
    units: str = ""
    values: List[str] = []
    while line != "*END":
        if line.startswith("!"):
            pass  # this is a comment, ignore the line
        elif line.startswith("*"):
            # convert previously read values (if any) and units to quantity
            if len(values) > 0:
                quantity = ureg.Quantity(np.array(values, dtype=float), units)
                _add_to_quantities(quantity=quantity, name=var)

            # this is a variable line, parse variable name and units
            var, units = _parse_var_line(line)

            # following lines are the variables values so prepare a variable
            # to store the values
            values = []
        else:
            if "!" in line:
                # this the line with the number of profile levels, ignore it
                pass
            else:
                # this line contains variable values
                values += _parse_values_line(line)
        line = next(iterator)

    # include last array of values before the '*END' line
    quantity = ureg.Quantity(np.array(values, dtype=float), units)
    _add_to_quantities(quantity=quantity, name=var)

    return quantities


def read_file_content(name: str) -> Tuple[str, Dict[str, str]]:
    """
    Read data file content.

    Parameters
    ----------
    name: str
        Atmospheric data file name.

    Returns
    -------
    tuple:
        file content, URL, URL date.
    """
    try:
        url = f"http://eodg.atm.ox.ac.uk/RFM/atm/{name}.atm"
        url_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        response = requests.get(url)
        content = response.text
        return content, dict(url=url, url_date=url_date)
    except requests.ConnectionError:
        file = f"{name}.atm"
        with pkg_resources.path(rfm, file) as path:
            with open(path, "r") as f:
                content = f.read()
        return content, dict()


def read_additional_species(
    name: str,
) -> Tuple[Dict[str, ureg.Quantity], Dict[str, str]]:
    """
    Read additional species data file.

    Parameters
    ----------
    name: str
        Atmospheric profile name in [``"day"``, ``"day_imk"``, ``"equ"``,
        ``"ngt"``, ``"ngt_imk"``, ``"sum"``, ``"sum_imk"``, ``"win"``,
        ``"win-imk"``, ``"mls"``, ``"mlw"``, ``"sas"``, ``"saw"``, ``"std"``,
        ``"tro"``].

    Returns
    -------
    tuple of dict of str and :class:`~pint.Quantity` and dict of str and str:
        Additional species parsed content, URL information.

    Raises
    ------
    ValueError
        If ``name`` is invalid.
    """
    if name in ["day", "equ", "ngt", "sum", "win"]:
        add_species_name = "extra"
    elif name in ["day_imk", "ngt_imk", "sum_imk", "win_imk"]:
        add_species_name = "extra_imk"
    elif name in ["mls", "mlw", "sas", "saw", "std", "tro"]:
        add_species_name = "minor"
    else:
        raise ValueError(f"invalid atmospheric profile name '{name}'")

    content, url_info = read_file_content(name=add_species_name)
    parsed_content = _parse_content(content.splitlines())
    return parsed_content, url_info


def read(name: str, additional_species: Optional[bool] = False) -> xr.Dataset:
    """Read RFM atmospheric data files.

    Try to read the data from http://eodg.atm.ox.ac.uk/RFM/atm/
    If that fails, reads archived data files in ``src/joseki/data/rfm/``.
    The archived raw data files were downloaded from
    http://eodg.atm.ox.ac.uk/RFM/atm/ on June 6th, 2021.

    Parameters
    ----------
    name: str
        Atmospheric profile name in [``"day"``, ``"day_imk"``, ``"equ"``,
        ``"ngt"``, ``"ngt_imk"``, ``"sum"``, ``"sum_imk"``, ``"win"``,
        ``"win-imk"``, ``"mls"``, ``"mlw"``, ``"sas"``, ``"saw"``, ``"std"``,
        ``"tro"``].

    additional_species: bool
        Set to ``True`` to include the additional species to the atmospheric
        profile.

    Returns
    -------
    :class:`~xarray.Dataset`
        Atmospheric profile.
    """
    content, url_info = read_file_content(name=name)
    url = url_info.get("url")
    url_date = url_info.get("url_date")
    quantities = _parse_content(content.splitlines())

    z_level = quantities.pop("z_level")
    p = quantities.pop("p")
    t = quantities.pop("t")
    n = p / (K * t)  # perfect gas equation
    species = np.array(list(quantities.keys()))
    mr = np.array([quantities[s].magnitude for s in species])

    if additional_species:
        extra_quantities, extra_url_info = read_additional_species(name=name)
        extra_z_level = extra_quantities.pop("z_level")
        extra_species = np.array(list(extra_quantities.keys()))
        extra_mr = np.array([extra_quantities[s].magnitude for s in extra_species])

        # initial species
        da = xr.DataArray(
            mr,
            dims=["species", "z_level"],
            coords={"species": species, "z_level": z_level.magnitude},
        )

        # additional species
        da_extra = xr.DataArray(
            extra_mr,
            dims=["species", "z_level"],
            coords={
                "species": extra_species,
                "z_level": extra_z_level.m_as(z_level.units),
            },
        )

        # interpolate additional species mixing ratio on altitude mesh used
        # for initial species mixing ratio:
        da_extra_interp = np.exp(
            np.log(da_extra).interp(z_level=z_level.m_as(z_level.units))
        )

        # concatenate initial and additional species
        da_total = xr.concat([da, da_extra_interp], dim="species")
        species = da_total.species.values
        mr = da_total.values

    ds: xr.Dataset = util.make_data_set(
        p=p,
        t=t,
        n=n,
        mr=mr,
        z_level=z_level,
        species=species,
        func_name="joseki.rfm.read",
        operation="data set creation",
        title=f"RFM {DESCRIPTION[name]} atmospheric profile",
        source=SOURCE,
        references=REFERENCE,
        url=url,
        url_date=url_date,
    )
    return ds