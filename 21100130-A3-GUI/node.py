import socket, pickle
from _thread import *
import os
from tkinter import *
import tkinter as tk
import threading
import time
from termcolor import colored
import sys, getopt
import hashlib
import copy

#0..2^m-1
m = 7 # if m = 7, keyspace is 0 to 127, size = 128 (2^m)
keyspace = 2**m # identifier circle
# each node is responsible for (1+E)K/N keys, where E = some constant, K = number of keys, N = nodes
isListening = False
isStabilizing = False

def send_packet(c_sock, packet):
    packet = str(len(packet)) + "%" + packet
    c_sock.sendall(packet.encode('utf-8')) # send list of body list strings in string form, encoded to bytestring
# just changed to send, careful!

def recv_packet(c_sock):
    try:
        testdata = c_sock.recv(1)
        if not testdata:
            return ""
        ps = testdata.decode('utf-8') # pick the first 1 byte (normal size of chars)
        while "%" not in ps:
            ps += c_sock.recv(2).decode('utf-8') # recieve 1 byte every time
        
        pslist = ps.split("%")
        packet_size = int(pslist[0])
        packet = pslist[1] # packet fragment that came with the %
        packet += c_sock.recv(packet_size).decode('utf-8')
    except socket.error:
        c_sock.shutdown(socket.SHUT_WR)
        c_sock.close()

    return packet

# for the set notation n IN (id, successor] etc. with wrap around
def in_set(between, left, right):
    if left < right:
        return (left < between and between < right)
    else:
        return (between < right or between > left)

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

def send_node_key(nodename, filename): # remember filename can be filepath here
    #print(f"Uploading {filename} to node {nodename}")
    file_size = os.path.getsize(filename)
    if file_size == 0:
        print("Empty file.")
        return

    #print(f"File size: {file_size}")
    packet = "@P," + filename + "," + str(file_size)
    server_ip, server_portstr = nodename.split(':')
    server_port = int(server_portstr)
    node_client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)    
    try:
        node_client_sock.connect((server_ip, server_port))
        send_packet(node_client_sock, packet)
        
        with open(filename, 'rb') as outfile:
           bytes_sent = node_client_sock.sendfile(outfile)

    #    print(f"Bytes sent: {bytes_sent}")
        if bytes_sent == file_size:
            print("File sending completed successfully.")
    except socket.error:
        return False
    return True

# each file is stored as the value in a key,value pair at the destined node
# temporary file naming convention is "filen.txt", where n = file number, 0,1,2..
# used for hashing both node names and file names    
def stringHasher(s):
    # encoding string to bytes, converting hexadecimal digest to decimal then taking % with keyspace to only keep max hash value then loop around ring
    # for compression across the ring, extra bits leading from m are truncated (converting to leading 0s actually)
    return int(hashlib.sha1(s.encode()).hexdigest(),16) % keyspace # m bit unsigned integer (only m bits are significant leftmost)

# there must be a Node class, of which an instance is created in the main
class Node():
    def __init__(self, given_ip, given_port):
        self.ip = given_ip
        self.port = given_port
        self.name = self.ip+':'+str(self.port) # distinct name
        self.id = stringHasher(self.name) # hash this name
        self.active = False
        self.predecessor = (-1,"") # not yet assigned
        # we already know the successor is in finger_table[1]
        self.successor = (-1,"") # not yet assigned
        self.successor_list = []
        # every node itself also participates as a key store
        self.keystore = {} # key, file_name pairs for every file stored at this node
        self.files_info = {} # dictionary containing dictionaries, more info about files here
        self.finger_table = [] # for every node there will be a finger table as a list of successors
        # first finger = node itself, second finger = immediate successor (self.id+1) # finger_table[1]
        for i in range(m): # m entries, i between 0 to m
            self.finger_table.append([]) 

        self.r = 8
        for i in range(self.r): # r successors
            self.successor_list.append([]) 
        self.node_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.node_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # reuse same ip:port
        try:
            self.node_sock.bind((given_ip, given_port))
        except socket.error:
            print("Unable to bind again, may already be in use.")
            quit()
        self.lt = threading.Thread(target=self.listener) # listener's thread created
        self.lt.daemon = True # prevent thread from running after program terminated
        self.st = threading.Thread(target=self.stabilizer) # stabilizer's thread created 
        self.st.daemon = True # prevent thread from running after program terminated
        
    def find_successor(self, key):
        # go back then check one step forward, if not ==, then go back more
        #1. find immediate predecessor node of desired id
        #2. successor of that node == id, return its name
        #print(f"Calculating successor for id {key}")
        successor_id = self.successor[0]
        # key in set (self.id, successor_id]
        if key == self.id:
            return self.name
        elif key == successor_id or in_set(key, self.id, successor_id):
            return self.successor[1]
        elif successor_id == self.predecessor[0]: # only one other node, this may not be needed
            if self.id > successor_id: # if my successor is < than my id
                if (key > self.id and key > successor_id) or (key < self.id and key < successor_id):
                    return self.successor[1]
                else:
                    return self.name
            elif successor_id > self.id and (self.id < key and key <= successor_id): # if my successor is greater than my id
                return self.successor[1]
            else:
                return self.name
        else:
            fwd_name = self.find_closest_preceding_node(key)  # forward request to node B, preceding node (largest hash, smaller than k)
            #print(f"Closest preceding node {fwd_name}")
            if fwd_name == "": # if forwarding node is same as this node, to prevent infinite recursion, forward query to successor
                fwd_name = self.successor[1] # my successor, try predecessor too
            
            #move query towards fwd name, cannot be handled by this node
            #print("Forwarding to", fwd_name)
            returned_successor = send_and_get_response(fwd_name, "@FS,"+str(key))
            #print("Returned successor", returned_successor)
            return returned_successor


    def find_closest_preceding_node(self, key):
        # finds a node n' such that the id falls between n' and the successor of n, then
        # find entry in finger table that closest and preferrably < id
        # Finding the largest hash smaller than the hash k
        i = m-1
        while (i >= 0):
            currFingerID = self.finger_table[i][0]
            if in_set(currFingerID, self.id, key):
                return self.finger_table[1][1]
            i -= 1
        return ""

    def get_id(self):
        return self.id


    def create(self):
        if self.active:
            return False

        self.active = True
        # disable create, join button
        # enable put, get buttons

        print(colored(f"Your node {self.name} created a network!", "green"))
        # all fingers should point to myself
        self.predecessor = (-1, "") # none
        self.successor = (self.id, self.name) # itself
        for i in range(self.r):
            self.successor_list[i] = [self.id, self.name]
        for i in range(len(self.finger_table)): # 1 to m, replace the node itself on all entries
            self.finger_table[i] = [self.id, self.name]

        global isListening
        global isStabilizing
        isListening = True
        isStabilizing = True
        self.lt.start()
        self.st.start()
    
    # Chord efficiently adapts as a node joins/leaves the system
    def join(self, joiner_name): # bootstrap, update other's finger_tables as well        
        if self.active:
            return False

        # disable create, join button
        # enable put, get buttons
        global isListening
        global isStabilizing
        isListening = True
        isStabilizing = True
        self.lt.start()
        print(colored(f"Joining the network using the node {joiner_name}.", "blue"))
        # update routing information -- finger table, keystore
        # certain keys previously assigned to this node’s successor now become assigned to it
        # when (n+1) node joins/leaves -> responsibility change
        # become aware of successor
        self.predecessor = (-1, "")
        newsuccessor = send_and_get_response(joiner_name, "@J,"+self.name)
        if newsuccessor != "":
            self.setSuccessor(newsuccessor)
            for i in range(len(self.finger_table)): # 1 to m, replace the node itself on all entries
                self.finger_table[i] = [self.successor[0], self.successor[1]]
        else:
            return False

        # initialise successor list to only successor
        for i in range(self.r):
            self.successor_list[i] = [self.successor[0], self.successor[1]]
        
        self.active = True
        self.st.start()
        print(colored("Join successful!", "green"))
        return True

    def notifySuccessor(self): # tell them to update their immediate predecessor, and get your predecessor
        if self.successor[1] == "":
            return False

        newpredecessor = send_and_get_response(self.successor[1], "@NSGP,"+self.name)
        if newpredecessor != "":
            self.setPredecessor(newpredecessor)

        return True

    def setSuccessor(self, new_successor_name):
        self.successor = (stringHasher(new_successor_name),new_successor_name)
        self.finger_table[0] = [self.successor[0], new_successor_name]
        self.successor_list[0] = [self.successor[0], new_successor_name]
    
    def setPredecessor(self, new_predecessor_name):
        self.predecessor = (stringHasher(new_predecessor_name),new_predecessor_name)
        
    def getActive(self):
        return self.active

    def checkNodeActive(self, nodename):
        if nodename == "":
            return False
        pings = 3
        while(pings != 0):
            response = send_and_get_response(nodename, "@A?")
            if response == "":
                return False
            elif response == "@Y":
                pings -= 1
            else:
                return False
            time.sleep(0.03) # delay between pings
        return True

    def isPredecessorActive(self):
        if self.predecessor[1] == "": # none predecessor
            return False
        if not self.checkNodeActive(self.predecessor[1]): # if not alive
            if (self.predecessor[1] == self.successor[1]): # there was only 1 other node, both successor and pred
                # then loop back successor to self
                self.setSuccessor(self.successor[1])
            self.predecessor = (-1, "") # none predecessor
            return False
        return True
    
    def fetch_node_succlist(self, nodename):
        bsucclist = send_and_get_response(nodename,"@GSL")
        if not bsucclist:
            return [] # empty list
        sslist = pickle.loads(bsucclist.encode())
        return sslist

    def isSuccessorActive(self):
        if self.successor[1] == "":
            return False

        self.successor_list[0] = [self.successor[0], self.successor[1]]
        current_successor = self.successor_list[0]
        while not self.checkNodeActive(current_successor[1]): 
            # until an alive successor is found in the list
            del self.successor_list[0] # delete head, current successor
            self.successor_list.append([]) # append a [] to keep the length of the list constant
            # new head checked now
            current_successor = self.successor_list[0] # head of successor list is always current successor
            if current_successor == []: # empty list, not going to happen with our assumption that there always exists one live node
                return False # stop if [] element reached

        slist = self.fetch_node_succlist(current_successor[1]); # slist fetched from live successor
        if slist == []:
            return False
        for i in range(1, self.r):
            self.successor_list[i] = slist[i-1]

        self.setSuccessor(self.successor_list[0][1])
        return True

    def fix_finger_table(self):
        for i in range(1,m):
            if not self.checkNodeActive(self.finger_table[i][1]): # if a node is not alive, stop there and return
                return False
            #every entry is the successor_of ((self.id+2**i)%keyspace)
            curr_id = (self.id + 2**i) % keyspace
            #print("Curr id",curr_id)
            entry_name = self.find_successor(curr_id)
            if entry_name == "": # successor not found
                return False
            #print("Entry name",entry_name)
            self.finger_table[i] = [stringHasher(entry_name), entry_name] 
        return True

    def fix_finger_table2(self):
        i = randint(1, m-1) # [1 to m-1] choose any finger to fix
        #every entry is the successor_of ((self.id+2**i)%keyspace)
        curr_id = (self.id + 2**i) % keyspace
        #print("Fixing for finger i ",curr_id)
        entry_name = self.find_successor(curr_id)
        if entry_name == "": # successor not found
            return False
        #time.sleep(0.5)
        #print("Entry name",entry_name)
        self.finger_table[i] = [stringHasher(entry_name), entry_name] 
        return True

    def stabilizer(self):
        global isStabilizing
        stabilizedTimes = 0
        AskedForFiles = False
        while isStabilizing:
            time.sleep(1) 
            stabilizedTimes += 1
            if stabilizedTimes % 10 == 0: # every 5 stabilization calls
                if not AskedForFiles: # every 5 stabilization calls
                    if self.successor[0] != self.id:
                        print ("Asking for files from successor.")
                        send_node_msg(self.successor[1], "@SMF,"+self.name) #@SENDMYFILES,MYNAME inform joiner node to send you your files
                        AskedForFiles = True
                self.finishAllDownloads()
                self.replicateCompletedFiles()
            self.isSuccessorActive() # successor lists
            self.isPredecessorActive()
            self.fix_finger_table() # refresh entire table, stop until alive node found
            #self.fix_finger_table2() # refresh random finger
            self.stabilize()
        print("Shutting down stabilization.")
            
    def stabilize(self):
        # ask successor about predecessor
        if self.successor[1] != "":
            successor_pred_x = send_and_get_response(self.successor[1], "@GP")
            # verifies if my immediate successor is consistent (no node x has come in between us, if it has that x is our successor)
            if successor_pred_x != "":
                x = stringHasher(successor_pred_x)
                if in_set(x, self.id, self.successor[0]):
                    self.setSuccessor(successor_pred_x)
            self.notifySuccessor()

    def leave(self):
        if not self.active:
            return False
        # enable create, join button
        # disable put, get button

        succ_name = self.successor[1]
        pred_name = self.predecessor[1]
        
        global isStabilizing 
        isStabilizing = False # breaks the stabilization
        self.st.join()

        print(f"Transferring keys to successor {succ_name}")
        # transfer all files from keystore to successor name
        for filename in self.keystore.values():
            send_node_key(succ_name, filename)
        self.keystore.clear() # clear key store after sending

        # send message to successor to update their predecessor to my predecessor
        if (succ_name != self.name and succ_name != ""):
            send_node_msg(succ_name, "@UP,"+pred_name)

        # send message to predecessor to update their successor to my successor
        if (pred_name != self.name and pred_name != ""):
            send_node_msg(pred_name, "@US,"+succ_name)
        
        self.finger_table.clear() # clear finger table
        for i in range(m): # m entries, i between 0 to m
            self.finger_table.append([]) #renew

        self.successor_list.clear() # clear successor list
        for i in range(self.r):
            self.successor_list.append([]) #renew

        print("Formally leaving the network.")
        global isListening
        isListening = False
        self.successor = (-1, "")
        self.predecessor = (-1, "")
        send_node_msg(self.name, "f") # if stuck in accept state, connect to self to move on
        self.lt.join()
        self.active = False
        #reassign socket and rebind
        self.node_sock.close() #just in case
        self.node_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.node_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # reuse same ip:port
        try:
            self.node_sock.bind((self.ip, self.port))
        except socket.error:
            ip_port = input("Unable to bind again, may already be in use. Enter new IP:PORT: ").split(":")
            self.node_sock.bind((ip_port[0], int(ip_port[1])))
            print("Bound successfully.")

        self.lt = threading.Thread(target=self.listener) # listener's thread recreated
        self.st = threading.Thread(target=self.stabilizer) # stabilizer's thread recreated
        # can answer queries even if the system is changing constantly

    def get_hashedName(self):
        # take hash of the given name
        return get_hashedName

    def put(self, filename):
        if not self.active:
            return False

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
        return send_node_key(file_successor_name, filename)
   
    def find_file_node(self, filename): # and add key file info to files_info
        key = stringHasher(filename) # get f_id
        targetNode = self.find_successor(key)
        tries = 5 # try 5 times, else file not found
        while tries >= 0:
            response = send_and_get_response(targetNode, "@HK?,"+str(key))
            rargs = response.split(",")
            if rargs[0] == "@N":
                targetNode = self.find_successor(stringHasher(targetNode)) # find the successor of that target node and restart process
                # overwrote targetNode, now target is their successor
            elif rargs[0] == "@Y":
                self.files_info[filename] = {"status":"Incomplete","size":int(rargs[1]),"recieved":0}
                return targetNode
            tries -= 1
        return "" # node with key not found


    def get_node_key(self, nodename, filename):
        f_id = stringHasher(filename)

        if f_id in self.keystore and self.getFileStatus(filename) == "Complete": # then must also exist in files_info
            print("The file is completely downloaded and present here. Cannot get again.")
            return False
        
        packet = "@G,"+str(f_id)
        server_ip, server_portstr = nodename.split(':')
        server_port = int(server_portstr)
        try:
            node_client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            node_client_sock.connect((server_ip, server_port))
            send_packet(node_client_sock, packet)
            chunk_size = 128 # 1024
            with open(filename, 'wb') as outfile: # for write
                while True:
                    chunk = node_client_sock.recv(chunk_size)
                    print(chunk)
                    if not chunk:
                        break
                    outfile.write(chunk)
        except socket.error:
            print("Socket error in get.")
            node_client_sock.shutdown(SHUT_WR)
            node_client_sock.close()

        self.keystore[f_id] = filename # added entry to keystore
        current_file_size = os.path.getsize(filename)
        # already have the original file size at the moment, so just update status with that and current file_size
        self.setFileInfo(filename, self.files_info[filename]["size"], current_file_size)

    def get(self, filename):
        if not self.active:
            return False

        if filename == "":
            return False

        f_id = stringHasher(filename)
        if f_id in self.keystore:
            print(f"This file is already present at this node.")
            return True

        file_owner_name = self.find_file_node(filename) # also updates files_info entry
        if file_owner_name == "":
            print(f"{filename} was not found.")
            return False

        return self.get_node_key(file_owner_name, filename)

    def printInfo(self):
        print(colored(f"NODE {self.id}", "yellow"))
        print(colored(f"SUCCESSOR: {self.successor}","yellow"))
        print(colored(f"PREDECESSOR: {self.predecessor}","yellow"))
        print(colored("SUCCESSOR LIST:", "blue"), self.successor_list)
        print(colored("FINGER TABLE:","red"), self.finger_table)
        print(colored("KEY STORE:","green"), self.keystore)
        print(colored("FILES INFO:","green"), self.files_info)
        print(colored(f"ACTIVE: {self.active}", "green"))

    def listener(self):
        # thread locks
        global isListening
        while isListening:
            self.node_sock.listen() # server will not start listening also until this parameter has been given
            if isListening == False:
                break

            try:
                client_sock, client_addr = self.node_sock.accept()
            except os.error:
                print("Lots of files open, quitting.")
                quit()     
            #print("Connection from %s" % str(client_addr))

            t = threading.Thread(target=self.taskHandler, args=(client_sock, client_addr,))
            t.start()

        self.node_sock.close()
        print("Shutting down listener.")
    

    def taskHandler(self, client_sock, client_addr):
        #recieving only here, no need to send data yet
        #print("A listening thread began.")
        try:
            packet = recv_packet(client_sock) # client's socket recieves data from the server script running on the server it connected to
            if packet == "":
                return False
        except error:
            print("Failed to recieve packet.")
            return False
        
        pargs = packet.split(',') # list of arguments obtained from packet
        task = pargs[0]
        if task == "@A?" and self.active: #@ALIVE?
            send_packet(client_sock, "@Y")

        elif task == "@FS": # find successor query
            #print(f"Find query recieved.",pargs)
            their_successor = self.find_successor(int(pargs[1]))
            send_packet(client_sock, their_successor)

        elif task == "@HK?": #@HAVEKEY?
            key = int(pargs[1])
            response = "@N,0"
            if key in self.keystore:
                filename = self.keystore[key] # then there must be a files_info entry as well, get fileSize from that
                response = "@Y,"+str(self.files_info[filename]["size"])
            send_packet(client_sock, response)

        # the node that said hi thinks he might be our predecessor
        elif task == "@NSGP": #@NOTIFY_SUCCESSOR_GET_PREDECESSOR
            new_pred_name = pargs[1]
            old_pred_name = self.predecessor[1]
            old_pred_id = self.predecessor[0]
            new_pred_id = stringHasher(new_pred_name)

            isCorrect = False # assumption to think they are my predecessor is false initially
            if old_pred_name == "":
                self.setPredecessor(new_pred_name)
                isCorrect = False
            elif old_pred_name == self.name or in_set(new_pred_id, old_pred_id, self.id):
                isCorrect = True
            
            if isCorrect:
                send_packet(client_sock, old_pred_name) # respond to new predecessor to update their predecessor to this node's old predecessor
                self.setPredecessor(new_pred_name)
            else:
                send_packet(client_sock, "")
            #print("My new predecessor: ", self.predecessor)
            
        elif task == "@GP": #@GET_PREDECESSOR
            send_packet(client_sock, self.predecessor[1])

        elif task == "@US": #@UPDATE_SUCCESSOR
            self.setSuccessor(pargs[1])
            #print("Updating to a new successor: ", self.successor)
        
        elif task == "@UP": #@UPDATE_PREDECESSOR
            self.setPredecessor(pargs[1])
            #print("Updating to a new predecessor: ", self.predecessor)
            
        elif task == "@P": #@PUT
            filename = pargs[1]
            file_size = int(pargs[2])
            f_id = stringHasher(filename)
            
            if f_id in self.keystore: #file already exists with me
                chunk_size = file_size # just recieve it all into void, lol
                try:
                    while True:
                        chunk = client_sock.recv(chunk_size)
                        if not chunk:
                            break
                except socket.error:
                    client_sock.shutdown(socket.SHUT_WR)
                    client_sock.close()
            else:
                # file must be atleast 8 bytes
                print(f"Downloading {filename}")
                self.keystore[f_id] = filename # added entry to keystore
                chunk_size = 128 # 1024
                try:
                    with open(filename, 'wb') as outfile:
                        while True:
                            chunk = client_sock.recv(chunk_size)
                            if not chunk:
                                break
                            outfile.write(chunk)
                except socket.error:
                    client_sock.shutdown(socket.SHUT_WR)
                    client_sock.close()

                current_file_size = os.path.getsize(filename)
                self.setFileInfo(filename, file_size, current_file_size)
            
        elif task == "@G": #@GET
            f_id = int(pargs[1])
            filename = self.keystore[f_id]
            print(f"Uploading {filename} to {client_addr} from the start.")
            try:
                file_size = os.path.getsize(filename)
                with open(filename, 'rb') as outfile:
                   bytes_sent = client_sock.sendfile(outfile, offset=0)

            except socket.error:
                client_sock.shutdown(socket.SHUT_WR)
                client_sock.close()
            
            print(f"Bytes sent: {bytes_sent}")
            if bytes_sent == file_size:
                print("File sending completed successfully.")
            else:
                print("Incomplete send executed.")

        elif task == "@PG": #@PARTIAL_GET
            f_id = int(pargs[1])
            filename = self.keystore[f_id]
            bytes_offset = int(pargs[2])
            print(f"Uploading {filename} to node {client_addr} resuming from bytes {bytes_offset}")
            try:
                # assuming the recieving end has the file size
                with open(filename, 'rb') as outfile:
                   bytes_sent = client_sock.sendfile(outfile, offset=bytes_offset)

            except socket.error:
                client_sock.shutdown(socket.SHUT_WR)
                client_sock.close()

        elif task == "@GSL": #@GET_SUCCESSOR_LIST
            send_packet(client_sock, pickle.dumps(self.successor_list, 0).decode()) # protocol 0 results in shorter bytestrings
        
        elif task == "@J": #@JOIN,33
            sender_name = pargs[1]
            sender_id = stringHasher(sender_name)
            their_successor = self.find_successor(sender_id)
            send_packet(client_sock, their_successor)
        
        elif task == "@SMF":
            sender_name = pargs[1]
            for key in self.keystore:
                if self.find_successor(key) == sender_name:
                    print(f"Replicating {self.keystore[key]} to {sender_name} because it belongs to them now.")
                    send_node_key(sender_name, self.keystore[key])
            
        client_sock.close()

    def getSuccessorName(self):
        return self.successor[1]

    def getSuccessorList(self):
        return self.successor_list

    def getFileStatus(self, filename):
        if filename in self.files_info:
            return self.files_info[filename]["status"]
        else:
            return ""

    def setFileInfo(self, filename, file_size, bytes_recv):
        self.files_info[filename] = {"status":"","size":file_size,"recieved":bytes_recv}
        if bytes_recv >= file_size:
            # if bytes_recv > file_size:
            #     self.files_info[filename]["recieved"] = file_size
            print("The whole file was recieved successfully.")
            self.files_info[filename]["status"] = "Complete" # status determined automatically
        else:
            print(f"The file was left incomplete.")
            self.files_info[filename]["status"] = "Incomplete"

    def finishAllDownloads(self):
        print("Resuming all downloads.")
        for filename in self.files_info:
            if self.getFileStatus(filename) == "Incomplete":
                print(f"Paused/incomplete download found for: \'{filename}\'")
                f_id = stringHasher(filename)
                nodename = self.find_file_node(filename)
                if nodename == "":
                    print(f"{filename} was not found. Deleting keystore and info entry.")
                    del self.files_info[filename]
                    del self.keystore[f_id]
                    return False

                packet = "@PG,"+str(f_id)+","+str(self.files_info[filename]["recieved"])
                server_ip, server_portstr = nodename.split(':')
                server_port = int(server_portstr)
                node_client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                node_client_sock.connect((server_ip, server_port))  # TCP - from the client side, we CONNECT to the given host and port
                send_packet(node_client_sock, packet)

                # request partial/remaining file again
                chunk_size = 128 # 1024
                current_file_size = os.path.getsize(filename)
                actual_file_size = self.files_info[filename]["size"]
                with open(filename, 'ab') as outfile: # for append
                    while True:
                        chunk = node_client_sock.recv(chunk_size)
                        if not chunk:
                            break
                        if current_file_size != actual_file_size:
                            outfile.write(chunk)

                current_file_size = os.path.getsize(filename)
                self.setFileInfo(filename, actual_file_size, current_file_size)

    def replicateCompletedFiles(self):
        print("Replicating completed downloads.")
        files_info_copy = copy.deepcopy(self.files_info)
        for filename in files_info_copy:
            if self.getFileStatus(filename) == "Complete":
                for successor in self.successor_list: # for every successor in successor list
                    if successor[0] != self.id:
                        if self.checkNodeActive(successor[1]): # if successor is alive
                            send_node_key(successor[1], filename) # send the successor the file as a put request

def configureOutputLabel1(message):
    output_label1.configure(text=message)

def callCreate():
    new_node.create()
    create_btn.configure(state=DISABLED)
    join_btn.configure(state=DISABLED)
    leave_btn.configure(state=NORMAL)
    put_btn.configure(state=NORMAL)
    get_btn.configure(state=NORMAL)

def callPrint():
    new_node.printInfo()

def callLeave():
    new_node.leave()
    create_btn.configure(state=NORMAL)
    join_btn.configure(state=NORMAL)
    leave_btn.configure(state=DISABLED)
    put_btn.configure(state=DISABLED)
    get_btn.configure(state=DISABLED)

host_ip, port = sys.argv[1], int(sys.argv[2])
root = tk.Tk() # create window
root.geometry('250x350') # dimensions
root.title("21100130_DC++")
root.resizable(False, False) # not resizable now both vertically and horizontally

btnFrame = tk.Frame(root) # frame widget on root window
#tk.widget_name(root_window, properties/configuration e.g. text for label widget)
output_label1 = tk.Label(root, text="OUTPUT HERE") # Label - text widget, pack method tells where to put the widget    
output_label1.pack()
print_btn = tk.Button(root, text="Print Node Info", command=callPrint) # Button widget created on root window
print_btn.pack()
create_btn = tk.Button(root, text="Create a Network", command=callCreate) # Button widget created on root window
create_btn.pack()
detail_label = tk.Label(root, text="IP:PORT:") # Label - text widget, pack method tells where to put the widget    
detail_label.pack()
join_entry = Entry(root, width=20, bg="black",fg="white")
join_entry.pack()

def callJoin():
    new_node.join(join_entry.get())
    create_btn.configure(state=DISABLED)
    join_btn.configure(state=DISABLED)
    leave_btn.configure(state=NORMAL)
    put_btn.configure(state=NORMAL)
    get_btn.configure(state=NORMAL)

join_btn = tk.Button(root, text="Join a Network", command=callJoin) 
join_btn.pack()
leave_btn = tk.Button(root, text="Leave",command=callLeave, state=DISABLED)
leave_btn.pack()
put_label = tk.Label(root, text="FILENAME:") # Label - text widget, pack method tells where to put the widget    
put_label.pack()
put_entry = Entry(root, width=20, bg="black",fg="white")
put_entry.pack()

def callPut():
    new_node.put(put_entry.get())

put_btn = tk.Button(root, text="Upload File", state=DISABLED, command=callPut)
put_btn.pack()
get_label = tk.Label(root, text="FILENAME:") # Label - text widget, pack method tells where to put the widget    
get_label.pack()
get_entry = Entry(root, width=20, bg="black",fg="white")
get_entry.pack()

def callGet():
    new_node.get(get_entry.get())

get_btn = tk.Button(root, text="Download File", state=DISABLED, command=callGet)
get_btn.pack()
# frame can be repositioned, so moving the UI widgets together is possible

#script for every node, main thing, whenever a node script is run, it goes online, connects to the network
# use gethostbyname for IP later
new_node = Node(host_ip, port) # listening starts right inside the constructor
configureOutputLabel1("NODE ID: "+str(new_node.get_id()))
#print(colored("Instructions:","red"))
#print("Create a network = c\nJoin a network = j IP:Port\nPrint Info = p\nLeave = l\nUpload a file = upload filename\nDownload a file = download filename\nClear screen = cls")
root.mainloop() # make sure the window stays
'''    
global user_input
userin = ""
while(True):
    print(userin)
    if userin[0] == "c": # create
        new_node.create()
    elif userin[0] == "j": # join
        if not new_node.join("127.0.0.1:"+str(userin[1])):
            print(colored("Failed to join the network.", "white"))
    elif userin[0] == "l":
        new_node.leave()
    elif userin[0] == "checkactive":
        if new_node.checkNodeActive(userin[1]):
            print(colored("Active.", "green"))
        else:
            print("Not active.")
    elif userin[0] == "p": # print
        new_node.printInfo()
    elif userin[0] == "cls":
        os.system('clear')
    elif userin[0] == "upload":
        new_node.put(userin[1])
    elif userin[0] == "download":
        new_node.get(userin[1])
    elif userin[0] == "finds":
        print(colored("Found successor:", "green"), stringHasher(new_node.find_successor(int(userin[1]))))
    elif userin[0] == "fad":
        new_node.finishAllDownloads()
    elif userin[0] == "findkeynode":
        print(colored(new_node.find_file_node(userin[1]), "green"))
    elif userin[0] == "replicate":
        new_node.replicateCompletedFiles()
'''