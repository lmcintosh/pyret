'''
spiketools.py

Tools for basic manipulation of spike trains

(c) 2014 bnaecker, nirum
'''

import numpy as _np
from scipy.io import loadmat as _loadmat
from scipy import signal as _signal

try:
    from peakdetect import peakdet
except ImportError:
    raise ImportError('You need to have the peakdetect module available on your python path. Download it here: https://raw.github.com/nirum/python-utils/master/peakdetect.py')

def binspikes(spk, tmax=None, binsize=0.01, time=None, numTrials=1):
    '''
    
    Bin spike times at the given resolution. The function has two forms.

    Input
    -----

    spk (ndarray):
        Array of spike times

    numTrials:
        How many trials went into this binning. The output counts are normalized such that they represent # of spikes / trial.
	
    EITHER:

        tmax (float):
            Maximum bin time. Usually end of experiment, but could
            really be anything.

        binsize (float):
            Size of bins (in milliseconds).

    OR:

        time (ndarray):
            The array to use as the actual bins to np.histogram

    Output
    ------

    bspk (ndarray):
        Binned spike times

    tax (ndarray):
        The bin centers

    '''

    # if time is not specified, create a time vector
    if time is None:

        # If a max time is not specified, set it to the time of the last spike
        if not tmax:
            tmax = _np.ceil(spk.max())

        # create the time vector
        time = _np.arange(0, tmax+binsize, binsize)

    # bin spike times
    bspk, _ = _np.histogram(spk, bins=time)

    # center the time bins
    tax = time[:-1] + 0.5*_np.mean(_np.diff(time))

    # returned binned spikes and cenetered time axis
    return bspk / numTrials, tax

def estfr(tax, bspk, sigma=0.01):
    '''
    
    Estimate the instantaneous firing rates from binned spike counts.

    Input
    -----
    tax:
        Array of time points corresponding to bins (as from binspikes)

    bspk:
        Array of binned spike counts (as from binspikes)

    sigma:
        The width of the Gaussian filter, in seconds

    mode (string):
        Mode of the convolution, one of 'valid', 'same', or 'full'.

    Output
    ------

    rates (ndarray):
        Array of estimated instantaneous firing rate

    '''

    # estimate binned spikes time step
    dt = _np.mean(_np.diff(tax))

    # Construct Gaussian filter, make sure it is normalized
    tau  = _np.arange(-5*sigma, 5*sigma, dt)
    filt = _np.exp(-0.5*(tau / sigma)**2)
    filt = filt / _np.sum(filt)
    size = _np.round(filt.size / 2)

    # Filter  binned spike times
    return _np.convolve(filt, bspk, mode='full')[size:size+tax.size] / dt

class spikingevent:
    '''

    The spiking event class bundles together functions that are used to analyze
    individual firing events, consisting of spiking activity recorded across trials / cells / conditions.

    Properties
    ----------

    start:
        the start time of the firing event

    stop:
        the stop time of the firing event

    spikes:
        the spikes associated with this firing event. This data is stored as an (n by 2) numpy array,
        where the first column is the set of spike times in the event and the second column is a list of
        corresponding trial/cell/condition indices for each spike

    '''

    def __init__(self, startTime, stopTime, spikes):
        self.start = startTime
        self.stop = stopTime
        self.spikes = spikes

    def __repr__(self):
        '''
        Printing this object prints out the start / stop time and number of spikes in the event
        '''
        return ('%5.2fs - %5.2fs (%i spikes)' % (self.start, self.stop, self.spikes.shape[0]))

    def __eq__(self, other):
        '''
        Equality between two spiking events is true if the start & stop times are the same
        '''
        return (self.start == other.start) & (self.stop == other.stop)

    def trialCounts(self):
        '''
        Count the number of spikes per trial

        Usage: counts = spkevent.trialCounts()

        '''
        counts, _ = _np.histogram(self.spikes[:,1], bins=_np.arange(_np.min(self.spikes[:,1]), _np.max(self.spikes[:,1])))
        return counts

    def eventStats(self):
        '''
        Compute statistics (mean and standard deviation) across trial spike counts

        Usage: mu, sigma = spkevent.trialStats()

        '''

        # count number of spikes per trial
        counts = self.eventCounts()

        return _np.mean(counts), _np.std(counts)

    def ttfs(self):
        '''
        Computes the time to first spike for each trial, ignoring trials that had zero spikes

        Usage: times = spkevent.ttfs()

        '''
        (trials, indices) = _np.unique(self.spikes[:,1], return_index=True)
        return self.spikes[indices,0]
    
    def jitter(self):
        '''
        Computes the jitter (standard deviation) in the time to first spike across trials

        Usage: sigma = spkevent.jitter()

        '''
        return _np.std(self.ttfs())

    def sort(self):
        '''
        Sort trial indices by the time to first spike

        Usage: sortedspikes = spkevent.sort()

        '''

        # get first spike in each trial
        _, trialIndices = _np.unique(self.spikes[:,1], return_index=True)

        # sort by time of first spike
        sortedIndices = _np.argsort(self.spikes[trialIndices, 0])

        # get reassigned trials
        sortedtrials = self.spikes[trialIndices[sortedIndices], 1]

        # store new spiking array, resetting trial numbers to the new index values
        sortedspikes = self.spikes.copy()
        for idx in range(sortedtrials.size):
            sortedspikes[self.spikes[:,1]==sortedtrials[idx],1] = idx+1

        return sortedspikes

    def plot(self, sort=False, ax=None, color='SlateGray'):
        '''
        Plots this event, as a spike raster

        Usage: spkevent.plot()

        '''
        import matplotlib.pyplot as _plt

        if sort:
            spikes = self.sort()
        else:
            spikes = self.spikes

        if not ax:
            ax = _plt.figure().add_subplot(111)

        ax.plot(spikes[:,0], spikes[:,1], 'o', markersize=6, markerfacecolor=color)

def detectevents(spk, threshold=(0.3,0.05)):
    '''

    Detects spiking events given a PSTH and spike times for multiple trials
    Usage: events = detectevents(spikes, threshold=(0.1, 0.005))

    Input
    -----
    spk:
        An (n by 2) array of spike times, indexed by trial / condition.
        The first column is the set of spike times in the event and the second column is a list of corresponding trial/cell/condition indices for each spike.

    Output
    ------
    events (list):
        A list of 'spikingevent' objects, one for each firing event detected.
        See the spikingevent class for more info.

    '''

    # find peaks in the PSTH
    bspk, tax = binspikes(spk[:,0], binsize=0.01, numTrials=_np.max(spk[:,1]))
    psth      = estfr(tax, bspk, sigma=0.005)
    maxtab, _ = peakdet(psth, threshold[0], tax)

    # store spiking events in a list
    events = list()

    # join similar peaks, define events
    for eventidx in range(maxtab.shape[0]):

        # get putative start and stop indices of each spiking event, based on the firing rate
        startIndices, = _np.where( (psth <= threshold[1]) & (tax < maxtab[eventidx,0]) )
        stopIndices,  = _np.where( (psth <= threshold[1]) & (tax > maxtab[eventidx,0]) )

        # find the start time, defined as the right most peak index
        starttime = tax[0] if startIndices.size == 0 else tax[_np.max(startIndices)]

        # find the stop time, defined as the lest most peak index
        stoptime = tax[-1] if  stopIndices.size == 0 else tax[_np.min(stopIndices )]

        # find spikes within this time interval (these make up the spiking event)
        eventSpikes = spk[(spk[:,0] >= starttime) & (spk[:,0] < stoptime),:]

        # create the spiking event
        myEvent = spikingevent(starttime, stoptime, eventSpikes)

        # only add it if it is a unique event
        if not events or not (events[-1] == myEvent):
            events.append(myEvent)

    return tax, psth, bspk, events