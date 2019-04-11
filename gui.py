import tkinter as tk

root = tk.Tk() # create window
root.geometry('300x300') # dimensions
root.title("First Tkinter Window")
root.resizable(False, False) # not resizable now both vertically and horizontally

myFrame = tk.Frame(root) # frame widget on root window
myFrame.pack()

#tk.widget_name(root_window, properties/configuration e.g. text for label widget)
tk.Label(myFrame, text="This is our first label").pack() # Label - text widget, pack method tells where to put the widget
tk.Button(myFrame, text="Hi, I'm a button.").pack() # Button widget created on root window
# frame can be repositioned, so moving the UI widgets together is possible

label2 = tk.Label(root, text="Label 2")
label2.pack() # configure variable later for the widget

root.mainloop() # make sure the window stays