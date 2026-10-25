# -*- coding: utf-8 -*-
"""UTM inverse for site latitude/longitude; never changes survey coordinates.

Sixth-order Kruger inverse, equations documented by PROJ:
https://proj.org/en/stable/operations/projections/tmerc.html
SIRGAS 2000 uses GRS80. No transformation between geodetic datums is applied.
"""
from __future__ import division, unicode_literals
import math
from topobim_core import finite


def validate_latlon(latitude, longitude):
    if not finite(latitude) or not -90 <= latitude <= 90:
        raise ValueError('Latitude deve estar entre -90 e 90 graus.')
    if not finite(longitude) or not -180 <= longitude <= 180:
        raise ValueError('Longitude deve estar entre -180 e 180 graus.')
    return float(latitude), float(longitude)


def utm_to_latlon(east, north, zone, hemisphere, datum):
    """Return (latitude, longitude), decimal degrees, in the declared datum."""
    name = ''.join(c for c in datum.upper() if c.isalnum())
    if name == 'SIRGAS2000':
        inverse_flattening = 298.257222101
    elif name == 'WGS84':
        inverse_flattening = 298.257223563
    else:
        raise ValueError('Cálculo automático disponível para SIRGAS 2000 e WGS 84. Para outro datum, informe latitude/longitude manualmente.')
    if zone != int(zone) or not 1 <= zone <= 60:
        raise ValueError('Zona UTM deve ser um inteiro de 1 a 60.')
    if hemisphere not in ('Sul', 'Norte'):
        raise ValueError('Hemisfério inválido.')
    if not finite(east) or not finite(north) or not (100000 <= east <= 900000 and 0 <= north <= 10000000):
        raise ValueError('A origem não tem coordenadas UTM válidas. Confira E/N, zona, hemisfério e unidade, ou informe latitude/longitude manualmente para coordenadas locais.')
    flattening = 1 / inverse_flattening
    n = flattening / (2 - flattening)
    eccentricity = math.sqrt(flattening * (2 - flattening))
    radius = 6378137 / (1 + n) * (1 + n**2 / 4 + n**4 / 64 + n**6 / 256)
    beta = (
        n/2 - 2*n**2/3 + 37*n**3/96 - n**4/360 - 81*n**5/512 + 96199*n**6/604800,
        n**2/48 + n**3/15 - 437*n**4/1440 + 46*n**5/105 - 1118711*n**6/3870720,
        17*n**3/480 - 37*n**4/840 - 209*n**5/4480 + 5569*n**6/90720,
        4397*n**4/161280 - 11*n**5/504 - 830251*n**6/7257600,
        4583*n**5/161280 - 108847*n**6/3991680,
        20648693*n**6/638668800)
    xi = (north - (10000000 if hemisphere == 'Sul' else 0)) / (0.9996 * radius)
    eta = (east - 500000) / (0.9996 * radius)
    xi_prime, eta_prime = xi, eta
    for index, coefficient in enumerate(beta, 1):
        xi_prime -= coefficient * math.sin(2 * index * xi) * math.cosh(2 * index * eta)
        eta_prime -= coefficient * math.cos(2 * index * xi) * math.sinh(2 * index * eta)
    chi = math.atan2(math.sin(xi_prime), math.sqrt(math.sinh(eta_prime)**2 + math.cos(xi_prime)**2))
    longitude = math.degrees(math.atan2(math.sinh(eta_prime), math.cos(xi_prime))) + zone * 6 - 183
    latitude = chi
    for _ in range(16):
        updated = math.atan(math.sinh(math.asinh(math.tan(chi)) +
                                     eccentricity * math.atanh(eccentricity * math.sin(latitude))))
        if abs(updated - latitude) < 1e-14:
            latitude = updated
            break
        latitude = updated
    latitude = math.degrees(latitude)
    if not -80.00000001 <= latitude <= 84.00000001:
        raise ValueError('Latitude calculada fora da faixa UTM (-80 a 84 graus). Confira as coordenadas.')
    if (hemisphere == 'Sul' and latitude > 1e-8) or (hemisphere == 'Norte' and latitude < -1e-8):
        raise ValueError('Coordenadas incompatíveis com o hemisfério informado.')
    longitude = (longitude + 180) % 360 - 180
    return validate_latlon(latitude, longitude)
