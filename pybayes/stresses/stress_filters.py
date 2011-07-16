# Copyright (c) 2010 Matej Laitl <matej@laitl.cz>
# Distributed under the terms of the GNU General Public License v2 or any
# later version of the license, at your option.

"""Stresses for kalman filters"""

import os.path
import time

import numpy as np

import pybayes as pb


DEBUG = False

def stress_kalman(options, timer):
    input_file = options.datadir + "/stress_kalman_data.mat"
    output_file = "stress_kalman_res.mat"

    run_kalman_on_mat_data(input_file, output_file, timer)

def run_kalman_on_mat_data(input_file, output_file, timer):
    # this should be here so that only this stress fails when scipy is not installed
    try:
        from scipy.io import loadmat, savemat
    except ImportError, e:
        raise StopIteration("Kalman filter stress needs scipy installed: " + str(e))

    d = loadmat(input_file, struct_as_record=True, mat_dtype=True)

    mu0 = np.reshape(d.pop('mu0'), (-1,))  # otherwise we would get 2D array of shape (1xN)
    P0 = d.pop('P0')
    y = d.pop('y').T
    u = d.pop('u').T

    gauss = pb.GaussPdf(mu0, P0)
    kalman = pb.KalmanFilter(d['A'], d['B'], d['C'], d['D'], d['Q'], d['R'], gauss)

    N = y.shape[0]
    n = mu0.shape[0]
    Mu_py = np.zeros((N, n))

    timer.start()
    for t in xrange(1, N):  # the 1 start offset is intentional
        kalman.bayes(y[t], u[t])
        Mu_py[t] = kalman.posterior().mu
    timer.stop()

    Mu_py = Mu_py.T
    savemat(output_file, {"Mu_py":Mu_py, "exec_time_pybayes":timer.spent[0]}, oned_as='row')

class PfOptionsA(object):
    """Class that represents options for a particle filter"""

    def __init__(self, nr_steps):
        print "Generating random data for particle filter stresses A..."
        self.nr_steps = nr_steps

        # prepare random vector components:
        a_t, b_t = pb.RVComp(1, 'a_t'), pb.RVComp(1, 'b_t')  # state in t
        a_tp, b_tp = pb.RVComp(1, 'a_{t-1}'), pb.RVComp(1, 'b_{t-1}')  # state in t-1

        # arguments to Kalman filter part of the marginalized particle filter
        self.kalman_args = {}

        # prepare callback functions
        sigma_sq = np.array([0.0001])
        def f(cond):  # log(b_{t-1}) - 1/2 \sigma^2
            return np.log(cond) - sigma_sq/2.
        def g(cond):  # \sigma^2
            return sigma_sq

        # p(a_t | a_{t-1} b_t) density:
        p_at_atpbt = pb.LinGaussCPdf(1., 0., 1., 0., pb.RV(a_t), pb.RV(a_tp, b_t))
        self.kalman_args['A'] = np.array([[1.]])  # process model
        # p(b_t | b_{t-1}) density:
        self.p_bt_btp = pb.GaussCPdf(1, 1, f, g, rv=pb.RV(b_t), cond_rv=pb.RV(b_tp), base_class=pb.LogNormPdf)
        # p(x_t | x_{t-1}) density:
        self.p_xt_xtp = pb.ProdCPdf((p_at_atpbt, self.p_bt_btp), pb.RV(a_t, b_t), pb.RV(a_tp, b_tp))

        # prepare p(y_t | x_t) density:
        self.p_yt_xt = pb.LinGaussCPdf(1., 0., 1., 0.)
        self.kalman_args['C'] = np.array([[1.]])  # observation model

        # Initial [a_t, b_t] from .. to:
        self.init_range = np.array([[-18., 0.3], [-14., 0.7]])
        init_mean = (self.init_range[0] + self.init_range[1])/2.

        x_t = np.zeros((nr_steps, 2))
        x_t[0] = init_mean.copy()
        y_t = np.empty((nr_steps, 1))
        for i in range(nr_steps):
            # set b_t:
            x_t[i,1] = i/100. + init_mean[1]
            # simulate random process:
            x_t[i,0:1] = p_at_atpbt.sample(x_t[i])  # this is effectively [a_{t-1}, b_t]
            y_t[i] = self.p_yt_xt.sample(x_t[i])
            # DEBUG: print "simulated x_{0} = {1}".format(i, x_t[i])
            # DEBUG: print "simulated y_{0} = {1}".format(i, y_t[i])
        self.x_t = x_t
        self.y_t = y_t

pf_nr_steps = 100  # number of steps for particle filter
pf_opts_a = PfOptionsA(pf_nr_steps)

def stress_pf_a_1(options, timer):
    run_pf(options, timer, pf_opts_a, 10, pb.ParticleFilter)

def stress_pf_a_1_marg(options, timer):
    run_pf(options, timer, pf_opts_a, 10, pb.MarginalizedParticleFilter)

def stress_pf_a_2(options, timer):
    run_pf(options, timer, pf_opts_a, 30, pb.ParticleFilter)

def stress_pf_a_2_marg(options, timer):
    run_pf(options, timer, pf_opts_a, 30, pb.MarginalizedParticleFilter)

def stress_pf_a_3(options, timer):
    run_pf(options, timer, pf_opts_a, 90, pb.ParticleFilter)

def stress_pf_a_3_marg(options, timer):
    run_pf(options, timer, pf_opts_a, 90, pb.MarginalizedParticleFilter)

def run_pf(options, timer, pf_opts, nr_particles, pf_class):
    nr_steps = pf_opts.nr_steps # number of time steps

    # prepare initial particle density:
    init_pdf = pb.UniPdf(pf_opts.init_range[0], pf_opts.init_range[1])

    # construct particle filter
    if pf_class is pb.ParticleFilter:
        pf = pf_class(nr_particles, init_pdf, pf_opts.p_xt_xtp, pf_opts.p_yt_xt)
    elif pf_class is pb.MarginalizedParticleFilter:
        pf = pf_class(nr_particles, init_pdf, pf_opts.p_bt_btp, pf_opts.kalman_args)
    else:
        raise NotImplementedError("This switch case not handled")

    x_t = pf_opts.x_t
    y_t = pf_opts.y_t
    cumerror = np.zeros(2)  # vector of cummulative square error
    timer.start()
    for i in range(nr_steps):
        if DEBUG:
            print "simulated x_{0} = {1}".format(i, x_t[i])
            print "simulated y_{0} = {1}".format(i, y_t[i])
        pf.bayes(y_t[i])
        apost = pf.posterior()
        cumerror += (apost.mean() - x_t[i])**2
        if DEBUG:
            print "returned mu_{0} = {1}".format(i, apost.mean())
            print
    timer.stop()
    print "  {0}-{3} cummulative error for {1} steps: {2}".format(
        nr_particles, nr_steps, np.sqrt(cumerror), pf_class.__name__)
