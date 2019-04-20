import sys, getopt
import socket, pickle
import hashlib
from _thread import *
import threading
import time
import os
from tkinter import *
import tkinter as tk

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
    testdata = c_sock.recv(1)
    if not testdata:
        return ""
    packet_size = testdata.decode('utf-8') # pick the first 1 byte (normal size of chars)
    while "%" not in packet_size:
        packet_size += c_sock.recv(1).decode('utf-8') # recieve 1 byte every time
    packet_size = int(packet_size[:-1])
    packet = c_sock.recv(packet_size).decode('utf-8')
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
    print(f"Uploading {filename} to node {nodename}")
    try:
        file_size = os.path.getsize(filename)
        if file_size == 0:
            print("Empty file.")
            return

        print(f"File size: {file_size}")
        packet = "@PUT," + filename + "," + str(file_size)
        server_ip, server_portstr = nodename.split(':')
        server_port = int(server_portstr)
        node_client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        node_client_sock.connect((server_ip, server_port))
        send_packet(node_client_sock, packet)
        
        with open(filename, 'rb') as outfile:
           bytes_sent = node_client_sock.sendfile(outfile)

        print(f"Bytes sent: {bytes_sent}")
        if bytes_sent == file_size:
            print("File sending completed successfully.")

    except socket.error:
        node_client_sock.shutdown(socket.SHUT_WR)
        node_client_sock.close()
        return False
    
    node_client_sock.shutdown(socket.SHUT_WR)
    node_client_sock.close()
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
        print(self.id)
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
        for i in range(10): # 10 successors
            self.successor_list.append([]) 
        self.node_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.node_sock.bind((given_ip, given_port))
        except socket.error:
            print("Unable to bind again, may already be in use.")
            quit()
        self.lt = threading.Thread(target=self.listener) # listener's thread created
        self.st = threading.Thread(target=self.stabilizer) # stabilizer's thread created 

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
        elif successor_id == self.predecessor[0]: # only one other node
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
            if fwd_name == self.name: # if forwarding node is same as this node, to prevent infinite recursion, forward query to successor
                fwd_name = self.successor[1] # my successor, try predecessor too
            
            #move query towards fwd name, cannot be handled by this node
            #print("Forwarding to", fwd_name)
            returned_successor = send_and_get_response(fwd_name, "@FINDS,"+str(key))
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
        return self.name

    def get_id(self):
        return self.id


    def create(self):
        if self.active:
            return False

        self.active = True
        # disable create, join button
        # enable put, get buttons

        print(f"This node {self.name} created a network.")
        # all fingers should point to myself
        self.predecessor = (-1, "") # none
        self.successor = (self.id, self.name) # itself
        for i in range(len(self.successor_list)):
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

        self.active = True
        # disable create, join button
        # enable put, get buttons
        
        global isListening
        global isStabilizing
        isListening = True
        isStabilizing = True
        self.lt.start()
        print(f"Joining the network using the node {joiner_name}.")
        # update routing information -- finger table, keystore
        # certain keys previously assigned to this node’s successor now become assigned to it
        # when (n+1) node joins/leaves -> responsibility change
        # be aware of successor
        self.predecessor = (-1, "")
        newsuccessor = send_and_get_response(joiner_name, "@JOIN,"+self.name)
        if newsuccessor != "":
            self.setSuccessor(newsuccessor)
            for i in range(len(self.finger_table)): # 1 to m, replace the node itself on all entries
                self.finger_table[i] = [self.successor[0], self.successor[1]]
        
        # initialise successor list to only successor
        for i in range(len(self.successor_list)):
            self.successor_list[i] = [self.successor[0], self.successor[1]]
        
        # if some of my keys belong to the new joiner, send them to him     
        for key in self.keystore: 
            if self.find_successor(key) == joiner_name:
                send_node_key(joiner_name, self.keystore[key])

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
        pings = 3
        while(pings != 0):
            response = send_and_get_response(nodename, "@ACTIVE?")
            if response == "":
                return False
            elif response == "@YESACTIVE":
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

    def fix_successor_list(self):
        slist = self.getSuccessorListFromNode(self.successor[1]);

        successor_list[1] = [self.successor[0], self.successor[1]];
        '''
        for i in range(2, 10):
        for(int i=2;i<=R;i++){
            successorList[i].first.first = list[i-2].first;
            successorList[i].first.second = list[i-2].second;
            successorList[i].second = help.getHash(list[i-2].first + ":" + to_string(list[i-2].second));
        '''
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
            #print("Curr id",curr_id)
            entry_name = self.find_successor(curr_id)
            if entry_name == "": # successor not found
                return False
            #print("Entry name",entry_name)
            self.finger_table[i] = [stringHasher(entry_name), entry_name] 
        return True

    def stabilizer(self):
        global isStabilizing
        while isStabilizing:
            time.sleep(0.5)
            #print("Stabilizing...")
            #self.isSuccessorActive() # successor lists
            self.isPredecessorActive()
            self.fix_finger_table()
            self.stabilize() #ruins my successor
        print("Shutting down stabilization.")
            
    def stabilize(self):
        # ask successor about predecessor
        if self.successor[1] != "":
            successor_pred_x = send_and_get_response(self.successor[1], "@GIVE_P")
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
            send_node_msg(succ_name, "@UPDATE_P,"+pred_name)

        # send message to predecessor to update their successor to my successor
        if (pred_name != self.name and pred_name != ""):
            send_node_msg(pred_name, "@UPDATE_S,"+succ_name)
        
        self.finger_table.clear() # clear finger table
        for i in range(m): # m entries, i between 0 to m
            self.finger_table.append([]) #renew

        print("Formally leaving the network.")
        global isListening
        isListening = False
        self.successor = (-1, "")
        self.predecessor = (-1, "")
        send_node_msg(self.name, "f") # if stuck in accept state, connect to self to move on
        self.lt.join()
        self.active = False
        #reassign socket and rebind
        self.node_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.node_sock.bind((self.ip, self.port))
        except socket.error:
            print("Unable to bind again, may already be in use.")
            quit()

        self.lt = threading.Thread(target=self.listener) # listener's thread recreated
        self.st = threading.Thread(target=self.stabilizer) # stabilizer's thread recreated

    #can answer queries even if the system is changing constantly

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
   
    def get_node_key(self, nodename, filename):
        f_id = stringHasher(filename)
        
        if f_id in self.keystore and self.getFileStatus(filename) == "Complete": # then must also exist in files_info
            print("The file is completely downloaded as well.")
            return False
        
        packet = "@GET,"+str(f_id)
        server_ip, server_portstr = nodename.split(':')
        server_port = int(server_portstr)
        try:
            node_client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            node_client_sock.connect((server_ip, server_port))
            send_packet(node_client_sock, packet)
            chunk_size = 128 # 1024
            with open(filename, 'wb') as outfile:
                while True:
                    chunk = node_client_sock.recv(chunk_size)
                    if not chunk:
                        break
                    outfile.write(chunk)
        except socket.error:
            node_client_sock.shutdown(SHUT_WR)
            node_client_sock.close()


        #file_size = int(recv_packet(node_client_sock))
        #print(f"File size: {file_size}")    
        self.keystore[f_id] = filename # added entry to keystore
        current_file_size = os.path.getsize(filename)
        print(current_file_size)
        self.setFileInfo(filename, 27, current_file_size)

    def get(self, filename):
        if not self.active:
            return False

        if filename == "":
            return False

        f_id = stringHasher(filename)
        if f_id in self.keystore:
            print(f"This file is already present at this node.")
            return True

        file_successor_name = self.find_successor(f_id)

        return self.get_node_key(file_successor_name, filename)

    def printInfo(self):
        print(f"NODE {self.id}:")
        print(f"ACTIVE: {self.active}")
        print(f"SUCCESSOR: {self.successor}")
        print(f"PREDECESSOR: {self.predecessor}")
        print("FINGER TABLE:", self.finger_table)
        print("KEY STORE:", self.keystore)
        print("FILES INFO:", self.files_info)

    def listener(self):
        # thread locks
        global isListening
        while isListening:
            self.node_sock.listen(10) # server will not start listening also until this parameter has been given
            if isListening == False:
                break
            client_sock, client_addr = self.node_sock.accept()
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
        except socket.error:
            print("Failed to recieve packet.")
            client_sock.shutdown(2)
            client_sock.close()
            return False
        

        pargs = packet.split(',') # list of arguments obtained from packet
        if pargs[0] == "@ACTIVE?" and self.active: #@ALIVE,192.168.0.1:5004
            send_packet(client_sock, "@YESACTIVE")

        elif pargs[0] == "@JOIN": #@JOIN,192.168.0.1:5004
            sender_id = stringHasher(pargs[1])
            send_packet(client_sock, self.find_successor(sender_id))
        
        elif pargs[0] == "@FINDS": # find successor query
            #print(f"Find query recieved.",pargs)
            their_successor = self.find_successor(int(pargs[1]))
            send_packet(client_sock, their_successor)

        # the node that said hi thinks he might be our predecessor
        elif pargs[0] == "@HI_S_GIVE_P": # notify
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
            
        elif pargs[0] == "@GIVE_P":
            send_packet(client_sock, self.predecessor[1])

        elif pargs[0] == "@UPDATE_S":
            self.setSuccessor(pargs[1])
            #print("Updating to a new successor: ", self.successor)
        
        elif pargs[0] == "@UPDATE_P":
            self.setPredecessor(pargs[1])
            #print("Updating to a new predecessor: ", self.predecessor)
            
        elif pargs[0] == "@PUT":
            filename = pargs[1]
            print(f"Downloading {filename}")
            file_size = int(pargs[2])
            f_id = stringHasher(filename)
            
            # file must be atleast 8 bytes
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
            
        elif pargs[0] == "@GET":
            f_id = int(pargs[1])
            filename = self.keystore[f_id]
            print(f"Sending {filename} to {client_addr}")
            try:
                file_size = self.files_info[filename]["size"]
                with open(filename, 'rb') as outfile:
                    bytes_sent = client_sock.sendfile(outfile)

            except socket.error:
                client_sock.shutdown(socket.SHUT_WR)
                client_sock.close()
            
            #abcdefghijklmnopqrstuvwxyz
            #print(f"File size: {file_size}")
            #send_packet(client_sock, str(file_size))
            print(f"Bytes sent: {bytes_sent}")
            if bytes_sent == file_size:
                print("File sending completed successfully.")
            else:
                print("Incomplete send executed.")

        elif pargs[0] == "@PARTGET":
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

        client_sock.close()
        return True    

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
        for filename in self.files_info:
            if self.getFileStatus(filename) == "Incomplete":
                f_id = stringHasher(filename)
                nodename = self.find_successor(f_id)
                packet = "@PARTGET,"+str(f_id)+","+str(self.files_info[filename]["recieved"])
                server_ip, server_portstr = nodename.split(':')
                server_port = int(server_portstr)
                node_client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                node_client_sock.connect((server_ip, server_port))  # TCP - from the client side, we CONNECT to the given host and port
                send_packet(node_client_sock, packet)

                # request partial/remaining file again
                chunk_size = 128 # 1024
                with open(filename, 'ab') as outfile: # for append
                    while True:
                        chunk = node_client_sock.recv(chunk_size)
                        if not chunk:
                            break
                        outfile.write(chunk)

                current_file_size = os.path.getsize(filename)
                self.setFileInfo(filename, self.files_info[filename]["size"], current_file_size)


def main(argv):
    host_ip, port = argv[0], int(argv[1]) # use all available IP addresses (both localhost and any public addresses configured)
    
    #script for every node, main thing, whenever a node script is run, it goes online, connects to the network
    # use gethostbyname for IP later
    new_node = Node(host_ip, port) # listening starts right inside the constructor
    '''
    root = tk.Tk() # create window
    root.geometry('300x300') # dimensions
    root.title("21100130-DC++")
    root.resizable(False, True) # not resizable now both vertically and horizontally

    detailFrame = tk.Frame(root) # frame widget on root window
    detail_label = tk.Label(detailFrame, text="DETAIL HERE") # Label - text widget, pack method tells where to put the widget    
    
    btnFrame = tk.Frame(root) # frame widget on root window
    #tk.widget_name(root_window, properties/configuration e.g. text for label widget)
    output_label = tk.Label(btnFrame, text="OUTPUT HERE") # Label - text widget, pack method tells where to put the widget    
    create_btn = tk.Button(btnFrame, text="Create", command=new_node.create()) # Button widget created on root window
    join_btn = tk.Button(btnFrame, text="Join") 
    leave_btn = tk.Button(btnFrame, text="Leave", state="disabled")
    put_btn = tk.Button(btnFrame, text="Put", state="disabled")
    get_btn = tk.Button(btnFrame, text="Get", state="disabled")
    # frame can be repositioned, so moving the UI widgets together is possible
    
    # pack, place, grid
    detailFrame.pack()
    detail_label.pack()
    #btnFrame.pack()
    btnFrame.place(bordermode=OUTSIDE, height=200, width=200, y=100, x=50)
    output_label.pack()
    create_btn.pack()
    join_btn.pack()
    leave_btn.pack()
    put_btn.pack()
    get_btn.pack()
    
    root.mainloop() # make sure the window stays
    '''
    while(True):
        userin = input(">> ").split(" ")
        if userin[0] == "create":
            new_node.create()
        elif userin[0] == "join":
            if not new_node.join("127.0.0.1:"+str(userin[1])):
                print("Failed to join the network.")
        elif userin[0] == "leave":
            new_node.leave()
        elif userin[0] == "msg":
            send_node_msg(userin[1], input("Enter message here: "))
        elif userin[0] == "checkactive":
            if new_node.checkNodeActive(userin[1]):
                print("That node is active.")
            else:
                print("Not active.")
        elif userin[0] == "print":
            new_node.printInfo()
        elif userin[0] == "cls":
            os.system('clear')
        elif userin[0] == "put":
            new_node.put(userin[1])
        elif userin[0] == "get":
            new_node.get(userin[1])
        elif userin[0] == "finds":
            print("Found successor:", stringHasher(new_node.find_successor(int(userin[1]))))
        elif userin[0] == "checkin":
            print(in_set(userin[1], userin[2], userin[3]))
        elif userin[0] == "fad":
            new_node.finishAllDownloads()

if __name__ == '__main__':
    main(sys.argv[1:])
