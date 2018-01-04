import os.path
from copy import deepcopy
import numpy as np
from scipy.io import loadmat


HERE = os.path.abspath(os.path.dirname(__file__))


def read_seatemp(obstype):
    """Grab squeezed variable and locs array from sea temperature MATLAB files
    """
    assert obstype.lower() in ['subt', 'sst']
    locs_template = 'locs_woa_1degree_asvec_{}.mat'
    var_template = 'st_woa_1degree_asvec_{}.mat'

    locs_path = None
    var_path = None
    if obstype == 'sst':
        locs_path = os.path.join(HERE, locs_template.format('SST'))
        var_path = os.path.join(HERE, var_template.format('SST'))
    elif obstype == 'subt':
        locs_path = os.path.join(HERE, locs_template.format('subT'))
        var_path = os.path.join(HERE, var_template.format('subT'))

    var = loadmat(var_path)['st_obs_ave_vec'].squeeze()
    locs = loadmat(locs_path)['locs_st_obs'].squeeze()

    return var, locs


def read_tex(obstype):
    """Grab squeezed variables array from TEX86 MATLAB files
    """
    var_template = 'Data_Input_SpatAg_{}.mat'
    var_path = None
    if obstype == 'sst':
        var_path = os.path.join(HERE, var_template.format('SST'))
    elif obstype == 'subt':
        var_path = os.path.join(HERE, var_template.format('subT'))
    locs = loadmat(var_path)['Data_Input']['Locs'].squeeze().item()
    obs_stack = loadmat(var_path)['Data_Input']['Obs_Stack'].squeeze().item()
    inds_stack = loadmat(var_path)['Data_Input']['Inds_Stack'].squeeze().item()
    return locs, obs_stack, inds_stack


def chord_distance(latlon1, latlon2):
    """Chordal distance between two groups of latlon points

    Parameters
    ----------
    latlon1 : ndarray
        An nx2 array of latitudes and longitudes for one set of points.
    latlon2 : ndarray
        An mx2 array of latitudes and longitudes for another set of points.

    Returns
    -------
    dists : 2d array
        An mxn array of Earth chordal distances [1]_ (km) between points in
        latlon1 and latlon2.

    References
    ----------
    .. [1] https://en.wikipedia.org/wiki/Chord_(geometry)

    """
    earth_radius = 6378.137  # in km

    assert latlon1.shape[1] == 2
    assert latlon2.shape[1] == 2

    n = latlon1.shape[0]
    m = latlon2.shape[0]

    paired = np.hstack((np.kron(latlon1, np.ones((m, 1))),
                        np.kron(np.ones((n, 1)), latlon2)))

    latdif = np.deg2rad(paired[:, 0] - paired[:, 2])
    londif = np.deg2rad(paired[:, 1] - paired[:, 3])

    a = np.sin(latdif / 2) ** 2
    b = np.cos(np.deg2rad(paired[:, 0]))
    c = np.cos(np.deg2rad(paired[:, 2]))
    d = np.sin(np.abs(londif) / 2) ** 2

    half_angles = np.arcsin(np.sqrt(a + b * c * d))

    dists = 2 * earth_radius * np.sin(half_angles)

    return dists.reshape(m, n)


class SeaTempObs:
    """Observed sea temperature fields as used in calibration
    """
    def __init__(self, st_obs_ave_vec, locs_st_obs):
        self.st_obs_ave_vec = np.array(st_obs_ave_vec)
        self.locs_st_obs = np.array(locs_st_obs)

    def distance_from(self, lat, lon):
        """Chordal distance (km) of observations from latlon

        Parameters
        ----------
        lat : float or int
        lon : float or int

        Returns
        -------
        d : ndarray
            An nx1 array of distances (km) between latlon and the (n) observed
            points.
        """
        lat = float(lat)
        lon = float(lon)
        latlon = np.array([[lat, lon]])
        d = chord_distance(latlon, self.locs_st_obs[:, ::-1])
        return d

    def get_close_obs(self, lat, lon, distance=500, min_obs=1):
        """Get observations closest to a latlon point

        Parameters
        ----------
        lat : float or int
        lon : float or int
        distance : float or int
            Distance (km) of buffer from latlon point.
        min_obs : int
            Minimum number of obs to collect, if not enough within distance.

        Returns
        -------
        obs_sorted : ndarray
            1d array of observation values within buffer. Sorted by distance
            from latlon.
        d_sorted : ndarray
            Corresponding 1d array of observation distances (km) from latlon.
            Sorted by distance
        """
        lat = float(lat)
        lon = float(lon)
        distance = float(distance)
        min_obs = int(min_obs)

        d = self.distance_from(lat, lon)
        assert d.size == self.st_obs_ave_vec.size

        sort_idx = np.argsort(d.flat, axis=0)
        d_sorted = d.flat[sort_idx]
        obs_sorted = self.st_obs_ave_vec[sort_idx]

        n_in_buffer = (d < distance).sum()
        assert n_in_buffer > 0

        msk = np.empty(self.st_obs_ave_vec.shape, dtype=bool)
        msk.fill(0)
        if n_in_buffer > min_obs:
            msk = d_sorted < distance
        else:
            msk[:min_obs] = True

        return obs_sorted[msk], d_sorted[msk]


class TexObs:
    """Observed TEX86 values"""
    def __init__(self, locs, obs_stack, inds_stack):
        self.locs = np.array(locs)
        self.obs_stack = np.array(obs_stack)
        self.inds_stack = np.array(inds_stack)

    def find_within_tolerance(self, x, tolerance):
        """Find mean TEX86 observations that are within ± tolerance from x

        Parameters
        ----------
        x : float
            Mean TEX86 value.
        tolerance : float
            Value added and subtracted from 'x' to get upper and lower tolerance
             bounds.

        Returns
        -------
        latlon_match : ndarray
            A 2d array (nx2) of latlon where matches were found.
        vals_match : ndarray
            A 1d array (n) of corresponding TEX86 averages from each match.
        """
        n_bg = len(self.locs)

        upper_bound = x + tolerance
        lower_bound = x - tolerance

        inder_g = []
        vals_match = []

        for kk in range(1, n_bg + 1):  # ...data was written to 1-based idx
            # Find the tex obs corresponding to this index location, using the
            # stacked obs:
            vals = self.obs_stack[self.inds_stack == kk]
            vals_mean = vals.mean()

            if lower_bound <= vals_mean <= upper_bound:
                idx = kk - 1  # Back to 0-based idx
                inder_g.append(idx)
                vals_match.append(vals_mean)

        latlon_match = self.locs[inder_g, ::-1]

        return latlon_match, np.array(vals_match)


seatemp_sst = SeaTempObs(*read_seatemp('sst'))
seatemp_subt = SeaTempObs(*read_seatemp('subt'))
tex_sst = TexObs(*read_tex('sst'))
tex_subt = TexObs(*read_tex('subt'))


def get_seatemp(obstype):
    """Get SeaTempObs instance for observation type"""
    if obstype == 'sst':
        return deepcopy(seatemp_sst)
    elif obstype == 'subt':
        return deepcopy(seatemp_subt)
    else:
        assert obstype in ['sst', 'subt']


def get_tex(obstype):
    """Get TexObs instance for observation type"""
    if obstype == 'sst':
        return deepcopy(tex_sst)
    elif obstype == 'subt':
        return deepcopy(tex_subt)
    else:
        assert obstype in ['sst', 'subt']
