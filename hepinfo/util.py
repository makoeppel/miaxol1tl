import h5py
import numpy as np
import awkward as ak


def readFromAnomalyh5(inputfile, process, object_ranges='default1', moreInfo=None, verbosity=0):
    """
    Reads data from h5s that either contain multiple signal processes or background that are loaded individually

    inputfile -- h5 file containing either background events or multiple signal processes
    process -- the name of the (signal) process, in case of reading a background file, please set this to 'background'
    object ranges -- dictionary containing the keys "met", "jets", "muons" and "egs" and for each key a tuple containing 
                     the range of the corresponding objects in the data array of the h5 file. For "met" it should be given
                     only the index (one number, no tuple), because by definition there can be only one MET object
                     Alternatively it can be set to the string "default1" (4 egs, 4 muons, 10 jets) or 
                     "default2" (12 egs, 8 muons, 12 jets)
    moreInfo -- more info about the data that is included in the output
    verbosity -- verbosity of this function
    """

    if(verbosity > 0): print("Reading anomaly team preprocessed file at " + inputfile + " for process " + process + ".")

    # constructing the information dict
    # some things will be automatically filled here
    # the input "moreInfo" can be used to pass more information
    # this information will have priority over automatically set entries
    infoDict = {}
    infoDict["input"] = inputfile

    # preparing lists to store L1 bit info
    L1bits_labels = []
    L1bits = []

    eventData = {} # initialize as empty in case file does not contain "event_info" key

    # reading the intput file
    if(verbosity > 0): print("Starting to read input file...")
    with h5py.File(inputfile, 'r') as h5f2:

        if process == 'background':
            for key in h5f2.keys():
                
                if key[:3] == "L1_":
                    L1bits_labels.append(key)
                    L1bits.append(np.array(h5f2[key]))
                elif key == "L1bit":
                    L1bit = np.array(h5f2[key])
                elif key == "event_info":
                    # Event info names taken from here: 
                    # https://gitlab.cern.ch/cms-l1-ad/l1tntuple-maker/-/blob/master/convert_to_h5.py#L125
#                     labels = ["run", "lumi", "event", "bx", "orbit", "time","nPV_True"] #deprecated
                    labels = ["run", "lumi", "event", "bx", "nPV", "nPV_Good"]
                    index = 0
                    for label in labels:
                        eventData[label] = h5f2[key][:,index]
                        index += 1

                if len(h5f2[key].shape) < 3: continue
                if key == "full_data_cyl":
                    data = h5f2[key][:,:,:].astype("float")
        else:
            if process not in h5f2.keys():
                raise ValueError(f'The process {process} is not contained in the file {inputfile}.')
            for key in h5f2.keys():
                
                if key.startswith(process + "_L1_"):
                    L1bits_labels.append(key.replace(process+"_", ""))
                    L1bits.append(np.array(h5f2[key]))
                elif key == process + "_l1bit":
                    L1bit = np.array(h5f2[key])

                # doing this should remove all trigger things, and leave a single entry with the data
                if len(h5f2[key].shape) < 3: continue
                if key == process: data = h5f2[key][:,:,:].astype("float")

    # splitting objects
    if object_ranges == 'default1':
        # we have 57 variables, but they do not have labels yet. Lets assign them based on the info in
        # https://gitlab.cern.ch/cms-l1-ad/l1_anomaly_ae/-/blob/master/in/prep_data.py
        # I assume that we have MET, 4 electrons, 4 muons and 10 jets
        # These are 19 objects, times 3 parameters -> 57 vars
        # From line 27 I think the order is as I listed it: MET, egs, muons, jets
        object_ranges = {'met': 0, 'egs': (1, 5), 'muons': (5, 9), 'jets': (9,19)}
        if verbosity > 0: print('Using the object ranges that are consistent with old h5 files provided by the anomaly detection team containing MET, 4 electrons, 4 muons and 10 jets in this order')
    elif object_ranges == 'default2':
        object_ranges = {'met': 0, 'egs': (1, 13), 'muons': (13, 21), 'jets': (21, 33)}
        if verbosity > 0: print('Using the object ranges that are consistent with new h5 files provided by the anomaly detection team containing MET, 12 electrons, 8 muons and 12 jets in this order')

    if verbosity > 0: print(f'Object ranges for reading the {process} dataset: {object_ranges}')

    np_sums = data[:,object_ranges['met'],:].reshape( (data.shape[0], 1, 3) ) # reshape is needed to keep dimensionality
    np_egs = data[:, object_ranges['egs'][0]:object_ranges['egs'][1]]
    np_muons = data[:, object_ranges['muons'][0]:object_ranges['muons'][1]]
    np_jets = data[:, object_ranges['jets'][0]:object_ranges['jets'][1]]

    # converting to awkward
    ak_egs = ak.zip( {key:ak.from_regular(np_egs[:,:,i], axis = 1) for i,key in enumerate(["pt","eta","phi"])}, with_name = "Momentum4D")
    ak_muons = ak.zip( {key:ak.from_regular(np_muons[:,:,i], axis = 1) for i,key in enumerate(["pt","eta","phi"])}, with_name = "Momentum4D")
    ak_jets = ak.zip( {key:ak.from_regular(np_jets[:,:,i], axis = 1) for i,key in enumerate(["pt","eta","phi"])}, with_name = "Momentum4D")

    # energy sums are handled a bit differently
    ak_sums = ak.zip( {key:ak.from_regular(np_sums[:,:,2*i], axis = 1) for i, key in enumerate(["pt","phi"])}, with_name = "Momentum4D")
    ak_sums["type"] = [2] * len(ak_sums) # MET should have Type 2

    # removing empty entries (not needed for energy sums)
    ak_egs = ak_egs[ak_egs.pt > 0]
    ak_muons = ak_muons[ak_muons.pt > 0]
    ak_jets = ak_jets[ak_jets.pt > 0]

    infoDict["nEvents"] = len(ak_muons)

    # formating the L1 bits
    d_bits = dict(zip(L1bits_labels, np.asarray(L1bits)))
    d_bits["total L1"] = L1bit
    df_bits = ak.zip(d_bits)
              
    # after everything else: add moreInfo
    if moreInfo: infoDict = {**infoDict, **moreInfo}
        
    if(verbosity > 0): print("Done!")
        
    # we'll output the data as a dict, makes it easier later
    dataDict = {}
    dataDict["muons"] = ak_muons
    dataDict["egs"] = ak_egs
    dataDict["jets"] = ak_jets
    dataDict["sums"] = ak_sums

    return infoDict, eventData, ak.Array(dataDict), df_bits


def readFromAnomalySignalh5(inputfile, process, object_ranges='default1', moreInfo=None, verbosity = 0):
    # object ranges -- dictionary containing the keys "met", "jets", "muons" and "egs" and for each key a tuple containing
    #                  the range of the corresponding objects in the data array of the h5 file. For "met" it should be given
    #                  only the index (one number, no tuple), because by definition there can be only one MET object
    #                  Alternatively it can be set to the string "default1" (4 egs, 4 muons, 10 jets) or 
    #                  "default2" (12 egs, 8 muons, 12 jets)

    return readFromAnomalyh5(inputfile, process, object_ranges, moreInfo, verbosity)


def readFromAnomalyBackgroundh5(inputfile, object_ranges='default1', moreInfo=None, verbosity = 0):
    # object ranges -- dictionary containing the keys "met", "jets", "muons" and "egs" and for each key a tuple containing
    #                  the range of the corresponding objects in the data array of the h5 file. For "met" it should be given
    #                  only the index (one number, no tuple), because by definition there can be only one MET object
    #                  Alternatively it can be set to the string "default1" (4 egs, 4 muons, 10 jets) or 
    #                  "default2" (12 egs, 8 muons, 12 jets)
    
    return readFromAnomalyh5(inputfile, 'background', object_ranges, moreInfo, verbosity)

def awkward_to_numpy(ak_array, maxN, verbosity = 0):
    # this is a bit ugly, but it works. Maybe we can improve later
    selected_arr = ak.fill_none( ak.pad_none( ak_array, maxN, clip=True, axis=-1), {"pt":0, "eta":0, "phi":0})
    np_arr = np.stack( (selected_arr.pt.to_numpy(), selected_arr.eta.to_numpy(), selected_arr.phi.to_numpy()), axis=2)
    return np_arr.reshape(np_arr.shape[0], np_arr.shape[1] * np_arr.shape[2])