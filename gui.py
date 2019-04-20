from tkinter import *
import tkinter as tk

def sample_function():
	print("created")

def main():
    root = tk.Tk() # create window
    root.geometry('300x300') # dimensions
    root.title("DC++")
    root.resizable(False, True) # not resizable now both vertically and horizontally

    detailFrame = tk.Frame(root) # frame widget on root window
    detail_label = tk.Label(detailFrame, text="DETAIL HERE") # Label - text widget, pack method tells where to put the widget    
    
    btnFrame = tk.Frame(root) # frame widget on root window
    #tk.widget_name(root_window, properties/configuration e.g. text for label widget)
    output_label = tk.Label(btnFrame, text="OUTPUT HERE") # Label - text widget, pack method tells where to put the widget    
    create_btn = tk.Button(btnFrame, text="Create", command=sample_function()) # Button widget created on root window
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
    
if __name__ == '__main__':
    main()