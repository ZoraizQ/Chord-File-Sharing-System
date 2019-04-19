import sys, getopt
import socket, pickle
import hashlib
from _thread import *
import threading
import time
import os

#0..2^m-1
m = 7 # if m = 7, keyspace is 0 to 127, size = 128 (2^m)
keyspace = 2**m # identifier circle
# each node is responsible for (1+E)K/N keys, where E = some constant, K = number of keys, N = nodes

def send_packet(c_sock, packet):
    packet = str(sys.getsizeof(packet)) + "%" + packet
    c_sock.sendall(packet.encode('utf-8')) # send list of body list strings in string form, encoded to bytestring

def recv_packet(c_sock):
    testdata = c_sock.recv(1)
    if not testdata:
        return ""
    packet_size = testdata.decode('utf-8') # pick the first 1 byte (normal size of chars)
    #print(packet_size)
    while "%" not in packet_size:
        packet_size += c_sock.recv(1).decode('utf-8') # recieve 1 byte every time
        #print(packet_size)

    packet_size = int(packet_size[:-1])
    packet = c_sock.recv(packet_size).decode('utf-8')
    return packet


def send_node_msg(name, packet):
    server_ip, server_portstr = name.split(':')
    server_port = int(server_portstr)
    try:
        node_client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        #print("Attempting to connect to %s on port %i." % (server_ip, server_port))
        node_client_sock.connect((server_ip, server_port))  # TCP - from the client side, we CONNECT to the given host and port
        # our client's port is decided arbitrarily by our computer e.g. 5192
    except socket.error: # comment
        #print("Unable to connect to the server.")
        return False

    send_packet(node_client_sock, packet)
    return True

def send_and_get_response(name, packet):
    #print(f"Sending {packet} to {name}")
    server_ip, server_portstr = name.split(':')
    server_port = int(server_portstr)
    try:
        node_client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        node_client_sock.connect((server_ip, server_port))  # TCP - from the client side, we CONNECT to the given host and port
        send_packet(node_client_sock, packet)
        response = recv_packet(node_client_sock)
        #print(f"Response recieved {response}")
    
    except socket.error: # comment
        #print("Unable to connect to the server.")
        return ""

    return response

def send_node_key(nodename, f_id, filename, file_contents):
    print(f"Uploading {filename} to node {nodename} with contents: ")
    print(file_contents)
    filePack = (filename, file_contents)
    send_node_msg(nodename, "@PUT," + pickle.dumps(filePack, 0).decode()) # using protocol 0 results in shorter strings
    # divide file into chunks later

# each file is stored as the value in a key,value pair at the destined node
# temporary file naming convention is "filen.txt", where n = file number, 0,1,2..
# used for hashing both node names and file names    
def stringHasher(s):
    s_hash = hashlib.sha1(s.encode()) # encoding string to bytes
    key = int(s_hash.hexdigest(),16) % keyspace # converting hexadecimal digest to decimal then taking % with keyspace to only keep max hash value then loop around ring
    # for compression across the ring, extra bits leading from m are truncated (converting to leading 0s actually)
    return key # m bit unsigned integer (only m bits are significant leftmost)

# there must be a Node class, of which an instance is created in the main
class Node():
    def __init__(self, given_ip, given_port):
        self.ip = given_ip
        self.port = given_port
        self.name = self.ip+':'+str(self.port) # distinct name
        self.id = stringHasher(self.name) # hash this name
        print(self.id)
        self.active = False
        self.predecessor = (-1,"") # not yet assigned
        # we already know the successor is in finger_table[1]
        self.successor = (-1,"") # not yet assigned
        # every node itself also participates as a key store
        self.keystore = {} # key, file_name pairs for every file stored at this node
        self.finger_table = [] # for every node there will be a finger table as a list of successors
        # first finger = node itself, second finger = immediate successor (self.id+1) # finger_table[1]
        for i in range(m): # m entries, i between 0 to m
            self.finger_table.append([]) 
        self.node_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.node_sock.bind((given_ip, given_port))
        self.lt = threading.Thread(target=self.listener) # listener's thread created
        self.st = threading.Thread(target=self.stabilizer) # stabilizer's thread created 


    def find_successor(self, _id):
        # go back then check one step forward, if not ==, then go back more
        #1. find immediate predecessor node of desired id
        #2. successor of that node == id, return its name
        #print(f"Calculating successor for id {_id}")
        successor_id = self.successor[0]
        if (_id <= successor_id and _id > self.id): # is my successor the owner of the id, check range
            return self.successor[1]
        elif self.id == successor_id: # is my id == my successor's (only node present) 
            return self.name
        elif _id == self.id: # is the id == my id,  when == as well this node successor to the id
            return self.name 
        elif successor_id == self.predecessor[0]: # only one other node
            if self.id > successor_id: # if my successor is < than my id
                if (_id > self.id and _id > successor_id) or (_id < self.id and _id < successor_id):
                    return self.successor[1]
                else:
                    return self.name
            elif successor_id > self.id and (self.id < _id and _id <= successor_id): # if my successor is greater than my id
                return self.successor[1]
            else:
                return self.name
        else:
            fwd_name = self.find_closest_preceding_node(_id)  # forward request to node B, preceding node (largest hash, smaller than k)
            print(f"Closest preceding node {fwd_name}")
            if (fwd_name == self.name): # if forwarding node is same as this node, to prevent infinite recursion, forward query to successor
                return self.successor[1] # my successor
            elif (fwd_name == ""): # could not find preceding node for this id, forward this query to the successor
                fwd_name = self.successor[1]
            # move query towards fwd name, cannot be handled by this node
            #print("Forwarding to", fwd_name)
            returned_successor = send_and_get_response(fwd_name, "@FINDS,"+str(_id))
            #print("Returned successor", returned_successor)
            return returned_successor


    def find_closest_preceding_node(self, _id):
        # finds a node n' such that the id falls between n' and the successor of n, then
        # find entry in finger table that closest and preferrably < id

        # Finding the largest hash smaller than the hash k
        pred_index = 0
        currFingerID = self.finger_table[0][0]
        mingap = abs(_id-currFingerID)
        for i in range(1, m-1):
            currFingerID = self.finger_table[i][0]
            currGap = abs(_id-currFingerID)
            if currGap < mingap and currFingerID <= _id:
                mingap = currGap
                pred_index = i

        if _id < self.finger_table[pred_index][0]:
            return ""
        else:
            return self.finger_table[pred_index][1]

    def get_id(self):
        return self.id


    def create(self):
        self.active = True
        print(f"This node {self.name} created a network.")
        # all fingers should point to myself
        self.predecessor = (self.id, self.name) # none
        self.successor = (self.id, self.name) # itself
        for i in range(len(self.finger_table)): # 1 to m, replace the node itself on all entries
            self.finger_table[i] = [self.id, self.name]

        self.lt.start()
        self.st.start()
    
    # Chord efficiently adapts as a node joins/leaves the system
    def join(self, joiner_name): # bootstrap, update other's finger_tables as well        
        self.active = True
        self.lt.start()
        print(f"Joining the network using the node {joiner_name}.")
        # update routing information -- finger table, keystore
        # certain keys previously assigned to this node’s successor now become assigned to it
        # when (n+1) node joins/leaves -> responsibility change
        # be aware of successor
        newsuccessor = send_and_get_response(joiner_name, "@JOIN,"+self.name)
        if newsuccessor != "":
            self.setSuccessor(newsuccessor)
            for i in range(len(self.finger_table)): # 1 to m, replace the node itself on all entries
                self.finger_table[i] = [self.successor[0], self.successor[1]]
        
        self.notifySuccessor()
        print(self.finger_table)
        self.st.start()
        return True
    
    def notifySuccessor(self): # tell them to update their immediate predecessor, and get your predecessor
        if self.successor[1] == "":
            return False

        newpredecessor = send_and_get_response(self.successor[1], "@HI_S_GIVE_P,"+self.name)
        if newpredecessor != "":
            self.setPredecessor(newpredecessor)

        return True

    def setSuccessor(self, new_successor_name):
        self.successor = (stringHasher(new_successor_name),new_successor_name)
        self.finger_table[0] = [self.successor[0], new_successor_name]
    
    def setPredecessor(self, new_predecessor_name):
        self.predecessor = (stringHasher(new_predecessor_name),new_predecessor_name)
        
    def getActive(self):
        return self.active

    def checkNodeActive(self, nodename):
        if nodename == "":
            return False
        pings = 0
        while(pings != 3):
            response = send_and_get_response(nodename, "@ACTIVE?")
            if response == "":
                return False
            elif response == "@YESACTIVE":
                pings += 1
            else:
                return False
        return True

    def isPredecessorActive(self):
        if self.predecessor[1] == "": # none predecessor
            return False
        if not self.checkNodeActive(self.predecessor[1]): # if not alive
            if (self.predecessor[1] == self.successor[1]): # there was only 1 other node, both successor and pred
                # then loop back successor to self
                self.setSuccessor(self.name)
                self.setPredecessor(self.name)
            self.predecessor = (-1, "") # none predecessor
            return False
        return True

    def isSuccessorActive(self):
        if self.successor[1] == "":
            return False

        if not self.checkNodeActive(self.successor[1]): # if not alive
            #self.setSuccessor(self.finger_table[0], self.finger_table[1])
            #print("Get successor")
            self.setSuccessor(self.find_successor(self.id))
            self.notifySuccessor()
            return False
        return True

    def fix_finger_table(self):
        for i in range(1,m):
            if not self.checkNodeActive(self.finger_table[i][1]): # if a node is not alive, stop there and return
                return False
            #every entry is the successor_of ((self.id+2**i)%keyspace)
            curr_id = (self.id + 2**i) % keyspace
            entry_name = self.find_successor(curr_id)
            if entry_name == "": # successor not foun
                return False
            self.finger_table[i] = [stringHasher(entry_name), entry_name] 
            return True


    def stabilizer(self):
        while(True):
            time.sleep(5)
            #self.isPredecessorActive()
            #self.isSuccessorActive() # successor lists
            #self.stabilize() #//
            #self.fix_finger_table()

    def stabilize(self):
        # ask successor about predecessor
        successor_pred_x = send_and_get_response(self.successor[1], "@GIVE_P")
        # verifies if my immediate successor is consistent (no node x has come in between us, if it has that x is our successor)
        if successor_pred_x != "":
            successor_pred_x_id = stringHasher(successor_pred_x)
            if (successor_pred_x_id > self.id and successor_pred_x_id < self.successor[0]):
                self.setSuccessor(successor_pred_x)
            self.notifySuccessor()

    def leave(self):
        print("Formally leaving the network.")
        #keys reassigned to successor, also transferred

    #can answer queries even if the system is changing constantly
        

    def get_hashedName(self):
        # take hash of the given name
        return get_hashedName

    def put(self, filename):
        if filename == "": # empty string for filename
            return False

        f_id = stringHasher(filename)
        print(f"File id: {f_id}")
        file_successor_name = self.find_successor(f_id)
        if file_successor_name == "":
            print("Error!")
            return False

        # parameter for who to recv from
        # file will be recieved as text string and stored as .txt
        fileHandler = open(filename, "r")
        file_contents = fileHandler.read()
        fileHandler.close()
        
        send_node_key(file_successor_name, f_id, filename, file_contents)
        return True
   
    def get_node_key(self, nodename, f_id):
        response = send_and_get_response(nodename, "@GET,"+str(f_id))
        obtained_filePack = pickle.loads(response.encode())
        filename = obtained_filePack[0]
        self.keystore[stringHasher(filename)] = filename # added entry to keystore
        return obtained_filePack[1]

    def get(self, filename):
        if filename == "":
            return False

        f_id = stringHasher(filename)
        if f_id in self.keystore:
            print(f"This file is already present at this node.")
            return True

        file_successor_name = self.find_successor(f_id)

        file_contents = self.get_node_key(file_successor_name, f_id)
        if file_contents != "":
            fileHandler = open(filename, "w")
            fileHandler.write(file_contents)
            fileHandler.close()
            return True
        else:
            return False

    def printInfo(self):
        print(f"NODE {self.id}:")
        print(f"ACTIVE: {self.active}")
        print(f"SUCCESSOR: {self.successor}")
        print(f"PREDECESSOR: {self.predecessor}")
        print("FINGER TABLE:", self.finger_table)
        print("KEY STORE:", self.keystore)

    def listener(self):
        # thread locks
        print("Listening for connections.")
        while True:
            self.node_sock.listen(5) # server will not start listening also until this parameter has been given
            client_sock, client_addr = self.node_sock.accept()
            #print("Connection from %s" % str(client_addr))

            t = threading.Thread(target=self.taskHandler, args=(client_sock, client_addr,))
            t.start()

        self.node_sock.close()
    

    def taskHandler(self, client_sock, client_addr):
        #recieving only here, no need to send data yet
        #print("A listening thread began.")
        try:
            packet = recv_packet(client_sock) # client's socket recieves data from the server script running on the server it connected to
            if packet == "":
                return False
        except socket.error:
            print("Failed to recieve packet.")
            client_sock.shutdown(2)
            client_sock.close()
            return False
        

        pargs = packet.split(',', 1) # list of 2 arguments obtained from packet
        if pargs[0] == "@ACTIVE?" and self.active: #@ALIVE,192.168.0.1:5004
            send_packet(client_sock, "@YESACTIVE")

        elif pargs[0] == "@JOIN": #@JOIN,192.168.0.1:5004
            sender_id = stringHasher(pargs[1])
            send_packet(client_sock, self.find_successor(sender_id))
        
        elif pargs[0] == "@FINDS": # find successor query
            #print(f"Find query recieved.")
            send_packet(client_sock, self.find_successor(int(pargs[1])))

        # the node that said hi thinks he might be our predecessor
        elif pargs[0] == "@HI_S_GIVE_P": # notify
            new_pred_name = pargs[1]
            old_pred_name = self.predecessor[1]
            new_pred_id = stringHasher(new_pred_name)

            send_node_msg(old_pred_name, "@UPDATE_S,"+new_pred_name) # tell old predecessor to update their successor to this node's new predecessor
            send_packet(client_sock, old_pred_name) # respond to new predecessor to update their predecessor to this node's old predecessor
            self.setPredecessor(new_pred_name)
            '''
            # if current predecessor is null, or new predecessor lies between the range of the old predecessor and self (exclusive)
            if self.predecessor[1] == "" or (new_pred_id > self.predecessor[0] and new_pred_id < self.id):
                #print("giving p and updating self p")
                if old_pred_name != "":
                    send_node_msg(old_pred_name, "@UPDATE_S,"+new_pred_name) # tell old predecessor to update their successor to this node's new predecessor
                send_packet(client_sock, old_pred_name) # respond to new predecessor to update their predecessor to this node's old predecessor
                self.setPredecessor(new_pred_name)
            else:
                send_packet(client_sock, "") # respond with "", to tell them they were wrong about thinking so, and should not change their predecessor
            #print("My new predecessor: ", self.predecessor)
            '''
        elif pargs[0] == "@GIVE_P":
            send_packet(client_sock, self.predecessor[1])

        elif pargs[0] == "@UPDATE_S":
            self.setSuccessor(pargs[1])
            #print("Updating to a new successor: ", self.successor)
        
        elif pargs[0] == "@UPDATE_P":
            self.setPredecessor(pargs[1])
            #print("Updating to a new predecessor: ", self.predecessor)
            
        elif pargs[0] == "@PUT":
            obtained_filePack = pickle.loads(pargs[1].encode())
            filename = obtained_filePack[0]
            self.keystore[stringHasher(filename)] = filename # added entry to keystore
            fileHandler = open(filename, "w")
            fileHandler.write(obtained_filePack[1])
            fileHandler.close()

        elif pargs[0] == "@GET":
            f_id = int(pargs[1])
            filename = self.keystore[f_id]
            fileHandler = open(filename, "r")
            file_contents = fileHandler.read()
            fileHandler.close()
            filePack = (filename, file_contents)
            send_packet(client_sock, pickle.dumps(filePack, 0).decode())

        client_sock.close()
        return True    


def main(argv):
    host_ip, port = argv[0], int(argv[1]) # use all available IP addresses (both localhost and any public addresses configured)
    
    #script for every node, main thing, whenever a node script is run, it goes online, connects to the network
    # use gethostbyname for IP later
    new_node = Node(host_ip, port) # listening starts right inside the constructor
    
    while(True):
        userin = input(">> ").split(" ")
        if (userin[0] == "create" and not new_node.getActive()):
            new_node.create()
        elif (userin[0] == "join" and not new_node.getActive()):
            if not new_node.join("127.0.0.1:"+str(userin[1])):
                print("Failed to join the network.")
        elif (userin == "leave" and new_node.getActive()):
            new_node.leave()
        elif (userin[0] == "msg"):
            send_node_msg(userin[1], input("Enter message here: "))
        elif(userin[0] == "checkactive"):
            if new_node.checkNodeActive(userin[1]):
                print("That node is active.")
            else:
                print("Not active.")
        elif (userin[0] == "print"):
            new_node.printInfo()
        elif (userin[0] == "cls"):
            os.system('clear')
        elif (userin[0] == "put" and new_node.getActive()):
            new_node.put(userin[1])
        elif (userin[0] == "get" and new_node.getActive()):
            new_node.get(userin[1])
        elif (userin[0] == "finds"):
            print("Found successor:",new_node.find_successor(int(userin[1])))

if __name__ == '__main__':
    main(sys.argv[1:])
