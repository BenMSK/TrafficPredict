import numpy as np
import torch
from torch.autograd import Variable
import matplotlib.pyplot as plt


def getVector(pos_list):
    """
    Gets the vector pointing from second element to first element
    params:
    pos_list : A list of size two containing two (x, y) positions
    """
    pos_i = pos_list[0]
    pos_j = pos_list[1]

    return np.array(pos_i) - np.array(pos_j)


def getMagnitudeAndDirection(*args):
    """
    Gets the magnitude and direction of the vector corresponding to positions
    params:
    args: Can be a list of two positions or the two positions themselves (variable-length argument)
    """
    if len(args) == 1:
        pos_list = args[0]
        pos_i = pos_list[0]
        pos_j = pos_list[1]

        vector = np.array(pos_i) - np.array(pos_j)
        magnitude = np.linalg.norm(vector)
        if abs(magnitude) > 1e-4:
            direction = vector / magnitude
        else:
            direction = vector
        return [magnitude] + direction.tolist()

    elif len(args) == 2:
        pos_i = args[0]
        pos_j = args[1]

        ret = torch.zeros(3)
        vector = pos_i - pos_j
        magnitude = torch.norm(vector)
        if abs(magnitude) > 1e-4:
            direction = vector / magnitude
        else:
            direction = vector

        ret[0] = magnitude
        ret[1:3] = direction
        return ret

    else:
        raise NotImplementedError(
            "getMagnitudeAndDirection: Function signature incorrect"
        )


def getCoef(outputs):
    """
    Extracts the mean, standard deviation and correlation
    params:
    outputs : Output of the SRNN model
    """
    mux, muy, sx, sy, corr = (
        outputs[:, :, 0],
        outputs[:, :, 1],
        outputs[:, :, 2],
        outputs[:, :, 3],
        outputs[:, :, 4],
    )

    # Exponential to get a positive value for std dev
    sx = torch.exp(sx)
    sy = torch.exp(sy)
    # tanh to get a value between [-1, 1] for correlation
    corr = torch.tanh(corr)
    return mux, muy, sx, sy, corr


def sample_gaussian_2d(mux, muy, sx, sy, corr, nodesPresent):
    """
    Returns samples from 2D Gaussian defined by the parameters
    params:
    mux, muy, sx, sy, corr : a tensor of shape 1 x numNodes
    Contains x-means, y-means, x-stds, y-stds and correlation
    nodesPresent : a list of nodeIDs present in the frame

    returns:
    next_x, next_y : a tensor of shape numNodes
    Contains sampled values from the 2D gaussian
    """
    o_mux, o_muy, o_sx, o_sy, o_corr = (
        mux[0, :],
        muy[0, :],
        sx[0, :],
        sy[0, :],
        corr[0, :],
    )
    nodesPresent = [t[0] for t in nodesPresent]
    numNodes = mux.size()[1]

    next_x = torch.zeros(numNodes)
    next_y = torch.zeros(numNodes)
    for node in range(numNodes):
        if node not in nodesPresent:
            continue
        mean = [o_mux[node], o_muy[node]]
        cov = [
            [o_sx[node] * o_sx[node], o_corr[node] * o_sx[node] * o_sy[node]],
            [o_corr[node] * o_sx[node] * o_sy[node], o_sy[node] * o_sy[node]],
        ]
        mean = [each.item() for each in mean]
        cov[0][0] = cov[0][0].item()
        cov[0][1] = cov[0][1].item()
        cov[1][0] = cov[1][0].item()
        cov[1][1] = cov[1][1].item()
        # why sampling...?
        next_values = np.random.multivariate_normal(mean, cov, 1)
    
        next_x[node] = mean[0]#next_values[0][0]
        next_y[node] = mean[1]#next_values[0][1]

    return next_x, next_y


def compute_edges(nodes, tstep, edgesPresent, use_cuda):
    """
    Computes new edgeFeatures at test time
    params:
    nodes : A tensor of shape seq_length x numNodes x 2
    Contains the x, y positions of the nodes (might be incomplete for later time steps)
    tstep : The time-step at which we need to compute edges
    edgesPresent : A list of tuples
    Each tuple has the (nodeID_a, nodeID_b) pair that represents the edge
    (Will have both temporal and spatial edges)

    returns:
    edges : A tensor of shape numNodes x numNodes x 2
    Contains vectors representing the edges
    """
    edgesPresent = [(t[0], t[1]) for t in edgesPresent]
    numNodes = nodes.size()[1]
    edges = torch.zeros(numNodes * numNodes, 2)
    if use_cuda:
        edges = edges.cuda()
    for edgeID in edgesPresent:
        nodeID_a = edgeID[0]
        nodeID_b = edgeID[1]

        if nodeID_a == nodeID_b:
            # Temporal edge
            pos_a = nodes[tstep - 1, nodeID_a, :]
            pos_b = nodes[tstep, nodeID_b, :]

            edges[nodeID_a * numNodes + nodeID_b, :] = pos_a - pos_b
            # edges[nodeID_a * numNodes + nodeID_b, :] = getMagnitudeAndDirection(pos_a, pos_b)
        else:
            # Spatial edge
            pos_a = nodes[tstep, nodeID_a, :]
            pos_b = nodes[tstep, nodeID_b, :]

            edges[nodeID_a * numNodes + nodeID_b, :] = pos_a - pos_b
            # edges[nodeID_a * numNodes + nodeID_b, :] = getMagnitudeAndDirection(pos_a, pos_b)

    return edges


def get_mean_error(ret_nodes, nodes, assumedNodesPresent, trueNodesPresent, use_cuda):
    """
    Computes average displacement error
    Parameters
    ==========

    ret_nodes : A tensor of shape pred_length x numNodes x 2
    Contains the predicted positions for the nodes

    nodes : A tensor of shape pred_length x numNodes x 2
    Contains the true positions for the nodes

    nodesPresent : A list of lists, of size pred_length
    Each list contains the nodeIDs of the nodes present at that time-step

    Returns
    =======

    Error : Mean euclidean distance between predicted trajectory and the true trajectory
    """
    assumedNodesPresent = [t[0] for t in assumedNodesPresent]
    trueNodesPresent = [[m[0] for m in t] for t in trueNodesPresent]
    pred_length = ret_nodes.size()[0]
    error = torch.zeros(pred_length)
    if use_cuda:
        error = error.cuda()
    counter = 0

    for tstep in range(pred_length):
        counter = 0
        for nodeID in assumedNodesPresent:

            if nodeID not in trueNodesPresent[tstep]:
                continue

            pred_pos = ret_nodes[tstep, nodeID, :]
            true_pos = nodes[tstep, nodeID, :]

            error[tstep] += torch.norm(pred_pos - true_pos, p=2)
            counter += 1

        if counter != 0:
            error[tstep] = error[tstep] / counter

    return torch.mean(error)

def visualization(ret_nodes, nodes, historyNodesPresent, assumedNodesPresent,\
     trueNodesPresent, obs_length, scale_param):#NOTE;; Ben

    min_position_x, min_position_y, max_position_x, max_position_y = scale_param


    observation_type = ['NONE', 'Pedestrian', 'Bicycle', 'Vehicle']

    assumed_ped_NodesPresent = [t[0] for t in assumedNodesPresent if int(t[1]) == 1]
    hist_ped_NodesPresent = [
        [m[0] for m in t if int(m[1] == 1)] for t in historyNodesPresent#1==pedestrians;t = frame
    ]
    true_ped_NodesPresent = [
        [m[0] for m in t if int(m[1] == 1)] for t in trueNodesPresent#1==pedestrians;t = frame
    ]

    assumed_bic_NodesPresent = [t[0] for t in assumedNodesPresent if int(t[1]) == 2]
    hist_bic_NodesPresent = [
        [m[0] for m in t if int(m[1] == 2)] for t in historyNodesPresent#1==pedestrians;t = frame
    ]
    true_bic_NodesPresent = [
        [m[0] for m in t if int(m[1] == 2)] for t in trueNodesPresent#2==bicycles
    ]

    assumed_car_NodesPresent = [t[0] for t in assumedNodesPresent if int(t[1] == 3)]
    hist_car_NodesPresent = [
        [m[0] for m in t if int(m[1] == 3)] for t in historyNodesPresent#1==pedestrians;t = frame
    ]
    true_car_NodesPresent = [
        [m[0] for m in t if int(m[1] == 3)] for t in trueNodesPresent#3==vehicles
    ]

    total_length = ret_nodes.size()[0]
    pred_length = total_length - obs_length
    future_ret_nodes = ret_nodes[obs_length:]
    future_nodes = nodes[obs_length:]

    ##NOTE: by Ben;;
    observations = {}
    results = {}
    ''' gt_trj = np.zeros((pred_length, 2))
        ft_trj = np.zeros((pred_length, 2))
        trj_results = [gt_trj, ft_trj]      '''
    for tstep in range(obs_length):#### HISTORY DATA GETTER
        
        for ped_nodeID in assumed_ped_NodesPresent:
            if ped_nodeID not in hist_ped_NodesPresent[tstep]:
                continue
            true_pos_ped = ret_nodes[tstep, ped_nodeID, :]

            if not ped_nodeID in observations.keys():## By BEN;; NOTE
                observations[ped_nodeID] = [np.zeros((obs_length, 2)), 1]
            observations[ped_nodeID][0][tstep,:] = true_pos_ped.cpu().numpy()

        for bic_nodeID in assumed_bic_NodesPresent:
            if bic_nodeID not in hist_bic_NodesPresent[tstep]:
                continue
            true_pos_bic = ret_nodes[tstep, bic_nodeID, :]

            if not bic_nodeID in observations.keys():## By BEN;; NOTE
                observations[bic_nodeID] = [np.zeros((obs_length, 2)), 2]
            observations[bic_nodeID][0][tstep,:] = true_pos_bic.cpu().numpy()

        for car_nodeID in assumed_car_NodesPresent:
            if car_nodeID not in hist_car_NodesPresent[tstep]:
                continue
            true_pos_car = ret_nodes[tstep, car_nodeID, :]
            
            if not car_nodeID in observations.keys():## By BEN;; NOTE
                observations[car_nodeID] = [np.zeros((obs_length, 2)), 3]
            observations[car_nodeID][0][tstep,:] = true_pos_car.cpu().numpy()

    for tstep in range(pred_length):
        
        for ped_nodeID in assumed_ped_NodesPresent:
            if ped_nodeID not in true_ped_NodesPresent[tstep]:
                continue
            pred_pos_ped = future_ret_nodes[tstep, ped_nodeID, :]
            true_pos_ped = future_nodes[tstep, ped_nodeID, :]

            if not ped_nodeID in results.keys():## By BEN;; NOTE
                results[ped_nodeID] = [np.zeros((pred_length, 2)), np.zeros((pred_length, 2)), 1]
            results[ped_nodeID][0][tstep,:] = true_pos_ped.cpu().numpy()
            results[ped_nodeID][1][tstep,:] = pred_pos_ped.cpu().numpy()

        for bic_nodeID in assumed_bic_NodesPresent:
            if bic_nodeID not in true_bic_NodesPresent[tstep]:
                continue
            pred_pos_bic = future_ret_nodes[tstep, bic_nodeID, :]
            true_pos_bic = future_nodes[tstep, bic_nodeID, :]

            if not bic_nodeID in results.keys():## By BEN;; NOTE
                results[bic_nodeID] = [np.zeros((pred_length, 2)), np.zeros((pred_length, 2)), 2]
            results[bic_nodeID][0][tstep,:] = true_pos_bic.cpu().numpy()
            results[bic_nodeID][1][tstep,:] = pred_pos_bic.cpu().numpy()

        for car_nodeID in assumed_car_NodesPresent:
            if car_nodeID not in true_car_NodesPresent[tstep]:
                continue
            pred_pos_car = future_ret_nodes[tstep, car_nodeID, :]
            true_pos_car = future_nodes[tstep, car_nodeID, :]
            
            if not car_nodeID in results.keys():## By BEN;; NOTE
                results[car_nodeID] = [np.zeros((pred_length, 2)), np.zeros((pred_length, 2)), 3]
            results[car_nodeID][0][tstep,:] = true_pos_car.cpu().numpy()
            results[car_nodeID][1][tstep,:] = pred_pos_car.cpu().numpy()
    
    ##VISUALIZATION;; NOTE
    for ID in results.keys():
        hist_gt = observations[ID][0]
        find_00 = hist_gt[:]!=np.array([0.0, 0.0])
        inds = [ i for i in range(find_00.shape[0]) if (find_00[i] != [False, False])[0] ]
        hist_gt = hist_gt[inds]
        # Scale up
        hist_gt[:,0] = (hist_gt[:,0]+1)*(max_position_x - min_position_x)/2 + min_position_x
        hist_gt[:,1] = (hist_gt[:,1]+1)*(max_position_y - min_position_y)/2 + min_position_y
        
        
        test_gt = results[ID][0]
        find_00 = test_gt[:]!=np.array([0.0, 0.0])
        inds = [ i for i in range(find_00.shape[0]) if (find_00[i] != [False, False])[0] ]
        test_gt = test_gt[inds]
        # Scale up
        test_gt[:,0] = (test_gt[:,0]+1)*(max_position_x - min_position_x)/2 + min_position_x
        test_gt[:,1] = (test_gt[:,1]+1)*(max_position_y - min_position_y)/2 + min_position_y
        test_gt = np.concatenate((np.expand_dims(hist_gt[-1,:], axis=0), test_gt), axis = 0)
        

        test_ft = results[ID][1]
        find_00 = test_ft[:]!=np.array([0.0, 0.0])
        inds = [ i for i in range(find_00.shape[0]) if (find_00[i] != [False, False])[0] ]
        test_ft = test_ft[inds]
        # Scale up
        test_ft[:,0] = (test_ft[:,0]+1)*(max_position_x - min_position_x)/2 + min_position_x
        test_ft[:,1] = (test_ft[:,1]+1)*(max_position_y - min_position_y)/2 + min_position_y
        test_ft = np.concatenate((np.expand_dims(hist_gt[-1,:], axis=0), test_ft), axis = 0)
        
        
        if observations[ID][1] == 1:#Peds
            plt.plot(hist_gt[:,0], hist_gt[:,1], 'o--k')
            plt.plot(test_gt[:,0], test_gt[:,1], '^-g')
            plt.plot(test_ft[:,0], test_ft[:,1], '^-r')
        elif observations[ID][1] == 2:#Bics
            plt.plot(hist_gt[:,0], hist_gt[:,1], 'o--k')
            plt.plot(test_gt[:,0], test_gt[:,1], '^-g')
            plt.plot(test_ft[:,0], test_ft[:,1], '^-r')
        elif observations[ID][1] == 3:#Bics
            plt.plot(hist_gt[:,0], hist_gt[:,1], 'o--k')
            plt.plot(test_gt[:,0], test_gt[:,1], '^-g')
            plt.plot(test_ft[:,0], test_ft[:,1], '^-r')
        
        x_diff = (test_gt[:,0] - test_ft[:,0])**2
        y_diff = (test_gt[:,1] - test_ft[:,1])**2
        dis_diff = np.sqrt(x_diff + y_diff)#distance^2
        ADE = np.mean(dis_diff)
        FDE = dis_diff[-1]


        xmin = min(min(hist_gt[:,0]), min(test_gt[:,0]), min(test_ft[:,0]))
        xmax = max(max(hist_gt[:,0]), max(test_gt[:,0]), max(test_ft[:,0]))
        ymin = min(min(hist_gt[:,1]), min(test_gt[:,1]), min(test_ft[:,1]))
        ymax = max(max(hist_gt[:,1]), max(test_gt[:,1]), max(test_ft[:,1]))
        STEP = 1.0

        _object = observation_type[observations[ID][1]]
        plt.title("Object Type: {}, ADE: {}, FDE: {}".format(_object, round(ADE,3), round(FDE,3)))
        # plt.xticks(np.arange(xmin-STEP, xmax+STEP, .5))
        # plt.yticks(np.arange(ymin-STEP, ymax+STEP, .5))
        
        plt.axis('equal')
        plt.show()
        
            



def get_mean_error_separately(
    ret_nodes, nodes, assumedNodesPresent, trueNodesPresent, use_cuda
):
    assumed_ped_NodesPresent = [t[0] for t in assumedNodesPresent if int(t[1]) == 1]
    true_ped_NodesPresent = [
        [m[0] for m in t if int(m[1] == 1)] for t in trueNodesPresent#1==pedestrians
    ]

    assumed_bic_NodesPresent = [t[0] for t in assumedNodesPresent if int(t[1]) == 2]
    true_bic_NodesPresent = [
        [m[0] for m in t if int(m[1] == 2)] for t in trueNodesPresent#2==bicycles
    ]

    assumed_car_NodesPresent = [t[0] for t in assumedNodesPresent if int(t[1] == 3)]
    true_car_NodesPresent = [
        [m[0] for m in t if int(m[1] == 3)] for t in trueNodesPresent#3==vehicles
    ]

    pred_length = ret_nodes.size()[0]

    error_ped = torch.zeros(pred_length)
    error_bic = torch.zeros(pred_length)
    error_car = torch.zeros(pred_length)

    if use_cuda:
        error_ped = error_ped.cuda()
        error_bic = error_bic.cuda()
        error_car = error_car.cuda()

    for tstep in range(pred_length):
        counter_ped = 0
        counter_bic = 0
        counter_car = 0
    
        for ped_nodeID in assumed_ped_NodesPresent:
            if ped_nodeID not in true_ped_NodesPresent[tstep]:
                continue
            pred_pos_ped = ret_nodes[tstep, ped_nodeID, :]
            true_pos_ped = nodes[tstep, ped_nodeID, :]
            error_ped[tstep] += torch.norm(pred_pos_ped - true_pos_ped, p=2)
            counter_ped += 1
        if counter_ped != 0:
            error_ped[tstep] = error_ped[tstep] / counter_ped#NOTE: Get Average;


        for bic_nodeID in assumed_bic_NodesPresent:
            if bic_nodeID not in true_bic_NodesPresent[tstep]:
                continue
            pred_pos_bic = ret_nodes[tstep, bic_nodeID, :]
            true_pos_bic = nodes[tstep, bic_nodeID, :]
            error_bic[tstep] += torch.norm(pred_pos_bic - true_pos_bic, p=2)
            counter_bic += 1
        if counter_bic != 0:
            error_bic[tstep] = error_bic[tstep] / counter_bic
        

        for car_nodeID in assumed_car_NodesPresent:
            if car_nodeID not in true_car_NodesPresent[tstep]:
                continue
            pred_pos_car = ret_nodes[tstep, car_nodeID, :]
            true_pos_car = nodes[tstep, car_nodeID, :]
            error_car[tstep] += torch.norm(pred_pos_car - true_pos_car, p=2)
            counter_car += 1
        if counter_car != 0:
            error_car[tstep] = error_car[tstep] / counter_car

    return torch.mean(error_ped), torch.mean(error_bic), torch.mean(error_car)


def get_final_error(ret_nodes, nodes, assumedNodesPresent, trueNodesPresent):
    """
    Computes final displacement error
    Parameters
    ==========

    ret_nodes : A tensor of shape pred_length x numNodes x 2
    Contains the predicted positions for the nodes

    nodes : A tensor of shape pred_length x numNodes x 2
    Contains the true positions for the nodes

    nodesPresent : A list of lists, of size pred_length
    Each list contains the nodeIDs of the nodes present at that time-step

    Returns
    =======

    Error : Mean final euclidean distance between predicted trajectory and the true trajectory
    """
    # nodesPresent = [[m[0] for m in t] for t in nodesPresent]

    assumedNodesPresent = [t[0] for t in assumedNodesPresent]
    trueNodesPresent = [[m[0] for m in t] for t in trueNodesPresent]

    pred_length = ret_nodes.size()[0]
    error = 0
    counter = 0

    # Last time-step
    tstep = pred_length - 1

    for nodeID in assumedNodesPresent:

        if nodeID not in trueNodesPresent[tstep]:
            continue

        pred_pos = ret_nodes[tstep, nodeID, :]
        true_pos = nodes[tstep, nodeID, :]

        error += torch.norm(pred_pos - true_pos, p=2)
        counter += 1

    if counter != 0:
        error = error / counter

    return error


def get_final_error_separately(ret_nodes, nodes, assumedNodesPresent, trueNodesPresent):
    """
    Computes final displacement error
    Parameters
    ==========

    ret_nodes : A tensor of shape pred_length x numNodes x 2
    Contains the predicted positions for the nodes

    nodes : A tensor of shape pred_length x numNodes x 2
    Contains the true positions for the nodes

    nodesPresent : A list of lists, of size pred_length
    Each list contains the nodeIDs of the nodes present at that time-step

    Returns
    =======

    Error : Mean final euclidean distance between predicted trajectory and the true trajectory
    """
    # nodesPresent = [[m[0] for m in t] for t in nodesPresent]

    # assumedNodesPresent = [t[0] for t in assumedNodesPresent]
    # rueNodesPresent = [[m[0] for m in t] for t in trueNodesPresent]

    assumed_ped_NodesPresent = [t[0] for t in assumedNodesPresent if int(t[1]) == 1]
    true_ped_NodesPresent = [
        [m[0] for m in t if int(m[1] == 1)] for t in trueNodesPresent
    ]

    assumed_bic_NodesPresent = [t[0] for t in assumedNodesPresent if int(t[1]) == 2]
    true_bic_NodesPresent = [
        [m[0] for m in t if int(m[1] == 2)] for t in trueNodesPresent
    ]

    assumed_car_NodesPresent = [t[0] for t in assumedNodesPresent if int(t[1] == 3)]
    true_car_NodesPresent = [
        [m[0] for m in t if int(m[1] == 3)] for t in trueNodesPresent
    ]

    pred_length = ret_nodes.size()[0]
    ped_error = 0
    bic_error = 0
    car_error = 0

    ped_counter = 0
    bic_counter = 0
    car_counter = 0

    # Last time-step
    tstep = pred_length - 1
    for ped_nodeID in assumed_ped_NodesPresent:
        if ped_nodeID not in true_ped_NodesPresent[tstep]:
            continue
        pred_pos_ped = ret_nodes[tstep, ped_nodeID, :]
        true_pos_ped = nodes[tstep, ped_nodeID, :]
        ped_error += torch.norm(pred_pos_ped - true_pos_ped, p=2)
        ped_counter += 1
    if ped_counter != 0:
        ped_error = ped_error / ped_counter

    for bic_nodeID in assumed_bic_NodesPresent:
        if bic_nodeID not in true_bic_NodesPresent[tstep]:
            continue
        pred_pos_bic = ret_nodes[tstep, bic_nodeID, :]
        true_pos_bic = nodes[tstep, bic_nodeID, :]
        bic_error += torch.norm(pred_pos_bic - true_pos_bic, p=2)
        bic_counter += 1
    if bic_counter != 0:
        bic_error = bic_error / bic_counter

    for car_nodeID in assumed_car_NodesPresent:
        if car_nodeID not in true_car_NodesPresent[tstep]:
            continue
        pred_pos_car = ret_nodes[tstep, car_nodeID, :]
        true_pos_car = nodes[tstep, car_nodeID, :]
        car_error += torch.norm(pred_pos_car - true_pos_car, p=2)
        car_counter += 1
    if car_counter != 0:
        car_error = car_error / car_counter
    return ped_error, bic_error, car_error


def sample_gaussian_2d_batch(
    outputs, nodesPresent, edgesPresent, nodes_prev_tstep, use_cuda
):
    mux, muy, sx, sy, corr = getCoef_train(outputs)

    next_x, next_y = sample_gaussian_2d_train(
        mux.data, muy.data, sx.data, sy.data, corr.data, nodesPresent
    )

    nodes = torch.zeros(outputs.size()[0], 2)
    nodes[:, 0] = next_x
    nodes[:, 1] = next_y

    nodes = Variable(nodes)
    if use_cuda:
        nodes = nodes.cuda()

    edges = compute_edges_train(nodes, edgesPresent, nodes_prev_tstep, use_cuda)

    return nodes, edges


def compute_edges_train(nodes, edgesPresent, nodes_prev_tstep, use_cuda):
    numNodes = nodes.size()[0]
    edges = Variable((torch.zeros(numNodes * numNodes, 2)))
    if use_cuda:
        edges = edges.cuda()
    for edgeID in edgesPresent:
        nodeID_a = edgeID[0]
        nodeID_b = edgeID[1]

        if nodeID_a == nodeID_b:
            # Temporal edge
            pos_a = nodes_prev_tstep[nodeID_a, :]
            pos_b = nodes[nodeID_b, :]

            edges[nodeID_a * numNodes + nodeID_b, :] = pos_a - pos_b
            # edges[nodeID_a * numNodes + nodeID_b, :] = getMagnitudeAndDirection(pos_a, pos_b)
        else:
            # Spatial edge
            pos_a = nodes[nodeID_a, :]
            pos_b = nodes[nodeID_b, :]

            edges[nodeID_a * numNodes + nodeID_b, :] = pos_a - pos_b
            # edges[nodeID_a * numNodes + nodeID_b, :] = getMagnitudeAndDirection(pos_a, pos_b)

    return edges


def getCoef_train(outputs):
    mux, muy, sx, sy, corr = (
        outputs[:, 0],
        outputs[:, 1],
        outputs[:, 2],
        outputs[:, 3],
        outputs[:, 4],
    )

    sx = torch.exp(sx)
    sy = torch.exp(sy)
    corr = torch.tanh(corr)
    return mux, muy, sx, sy, corr


def sample_gaussian_2d_train(mux, muy, sx, sy, corr, nodesPresent):
    o_mux, o_muy, o_sx, o_sy, o_corr = mux, muy, sx, sy, corr

    numNodes = mux.size()[0]

    next_x = torch.zeros(numNodes)
    next_y = torch.zeros(numNodes)
    for node in range(numNodes):
        if node not in nodesPresent:
            continue
        
        mean = [o_mux[node], o_muy[node]]
        cov = [
            [o_sx[node] * o_sx[node], o_corr[node] * o_sx[node] * o_sy[node]],
            [o_corr[node] * o_sx[node] * o_sy[node], o_sy[node] * o_sy[node]],
        ]

        next_values = np.random.multivariate_normal(mean, cov, 1)# sampling!
        next_x[node] = next_values[0][0]
        next_y[node] = next_values[0][1]

    return next_x, next_y
