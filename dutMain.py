#!/usr/bin/env python
#
# Script to record webcam and screencast
#
# Copyright 2012 Intel Corporation.
#
# Author: Michael Wood <michael.g.wood@intel.com>
#
# This program is free software; you can redistribute it and/or modify it
# under the terms and conditions of the GNU Lesser General Public License,
# version 2.1, as published by the Free Software Foundation.
#
# This program is distributed in the hope it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program; if not, see <http://www.gnu.org/licenses>
#


try:
    from gi.repository import Gtk
except ImportError:
    print ("Gtk3 introspection not found try installing gir-gtk-3.0 or similar")
    exit ()

# These are dependencies of Gtk so they should exist if Gtk does
from gi.repository import GLib
from gi.repository import Gdk
from gi.repository import Gio

try:
    import gst
except ImportError:
    print ("Python gst not found try installing python-gst or similar")
    exit ()

import time
import shutil
from datetime import timedelta

import subprocess
import dutWebcamRecord
import dutScreencastRecord
import dutMux
import dutNewRecording
import dutProject

class m:
    TITLE, DATE, DURATION, EXPORT, DELETE, PROGRESS = range (6)

class dutMain:
    def __init__(self):

        self.webcam = None
        self.screencast = None
        self.mux = None
        self.dut = None
        self.projectDir = None
        self.projectLabel = None
        self.listStore = None
        self.buttonBox = None
        self.screen = None
        self.projectConfig = None
        self.encodeButton = None
        self.recordButton = None
        self.mainWindow = None
        self.updateTimer = None
        self.encodeQueue = []
        self.listItr = None

        self.icon = Gtk.StatusIcon (visible=False)
        self.icon.set_from_stock (Gtk.STOCK_MEDIA_RECORD)
        self.icon.connect ("activate", self.stop_record)

        self.mainWindow = Gtk.Window(title="Dawati user testing tool",
                                     resizable=False,
                                     icon_name=Gtk.STOCK_MEDIA_RECORD)
        self.mainWindow.connect("destroy", self.on_mainWindow_destroy)

        outterBoxLayout = Gtk.VBox (spacing=5, homogeneous=False)

        menu = Gtk.Toolbar ()
        menu.get_style_context ().add_class (Gtk.STYLE_CLASS_PRIMARY_TOOLBAR)

        fileNew = Gtk.ToolButton.new_from_stock ("gtk-new")
        fileNew.set_label ("New project")
        fileNew.connect ("clicked", self.new_folder_chooser, self.mainWindow)

        fileOpen = Gtk.ToolButton.new_from_stock ("gtk-open")
        fileNew.set_label ("Open project")
        fileOpen.connect ("clicked", self.open_file_chooser, self.mainWindow)

        menu.insert (fileNew, 0)
        menu.insert (fileOpen, 1)

        dateLabel = Gtk.Label ("Date")
        durationLabel = Gtk.Label ("Duration")

        self.projectLabel = Gtk.Label (halign=Gtk.Align.START)
        self.projectLabel.set_markup ("<span style='italic'>No project open</span>")

        self.recordButton = Gtk.Button (label="Create recording",
                                        tooltip_text="Create a new recording",
                                        sensitive=False)
        self.recordButton.connect("clicked", self.new_record_button_clicked_cb)

        self.encodeButton = Gtk.Button (label="Export",
                                        tooltip_text="Encode selected sessions",
                                        sensitive=False)
        self.encodeButton.connect("clicked", self.encode_button_clicked_cb)

        self.recordingDeleteButton = Gtk.Button (label="Delete",
                                            tooltip_text="Delete selected sessions",
                                            sensitive=False)

        self.recordingDeleteButton.connect("clicked", self.delete_button_clicked_cb)

        self.listStore = Gtk.ListStore (str, str, int, bool, bool, int)


        recordingsView = Gtk.TreeView (model=self.listStore)
        recordingsView.connect ("row-activated", self.row_activated)

        # Column Recording Name
        recordingTitle = Gtk.CellRendererProgress (text_xalign=0)
        col1 = Gtk.TreeViewColumn ("Recording name",
                                   recordingTitle,
                                   text=m.TITLE,
                                   value=m.PROGRESS)
        recordingsView.append_column (col1)

        # Column Date
        recordingDate = Gtk.CellRendererText ()
        col2 = Gtk.TreeViewColumn ("Date", recordingDate, text=m.DATE)
        recordingsView.append_column (col2)

        # Column Duration
        recordingDuration = Gtk.CellRendererText (xalign=0)
        col3 = Gtk.TreeViewColumn ("Duration", recordingDuration,
                                   text=m.DURATION)
        recordingsView.append_column (col3)
        col3.set_cell_data_func(recordingDuration,
                                lambda column, cell, model, iter, data:
                                cell.set_property('text',
                                                  str(timedelta (seconds=model.get_value (iter, m.DURATION))))

                               )

        # Column for export
        recordingExport = Gtk.CellRendererToggle (xalign=0.5)
        recordingExport.connect ("toggled", self.export_toggled)
        col4 = Gtk.TreeViewColumn ("Export", recordingExport, active=m.EXPORT)
        recordingsView.append_column (col4)
        col4.connect ("notify::x-offset", self.buttons_x_offset)

        # Column for delete
        recordingDelete = Gtk.CellRendererToggle (xalign=0.5)
        recordingDelete.connect ("toggled", self.delete_toggled)
        col5 = Gtk.TreeViewColumn ("Delete", recordingDelete, active=m.DELETE)
        recordingsView.append_column (col5)

        # Box for new recording, export and delete buttons
        self.buttonBox = Gtk.HBox (spacing=5, homogeneous=False)
        self.buttonBox.pack_start (self.recordButton, False, False, 3)
        self.buttonBox.pack_start (self.encodeButton, False, False, 3)
        self.buttonBox.pack_start (self.recordingDeleteButton, False, False, 3)
        self.buttonBox.hide ()

        # Box for rest of the UI which doesn't span the whole window
        innerVbox = Gtk.VBox (spacing=5,
                              homogeneous=False,
                              margin_left=5,
                              margin_right=5)

        innerVbox.pack_start (self.projectLabel, False, False, 3)
        innerVbox.pack_start (recordingsView, False, False, 3)
        innerVbox.pack_start (self.buttonBox, False, False, 3)


        # Main container in window
        outterBoxLayout.pack_start (menu, False, False, 3)
        outterBoxLayout.pack_start (innerVbox, False, False, 3)

        self.mainWindow.add(outterBoxLayout)
        self.mainWindow.show_all()

    def notification (self, title, message):
        d = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        notify = Gio.DBusProxy.new_sync(d, 0, None,
                                        'org.freedesktop.Notifications',
                                        '/org/freedesktop/Notifications',
                                        'org.freedesktop.Notifications', None)

        notify.Notify('(susssasa{sv}i)', 'dawati-user-testing', 1, 'gtk-ok',
                      title, message,
                      [], {}, 10000)


    def row_activated (self, tree, path, col):
        if self.listStore[path][m.PROGRESS] == 100:
            uri = GLib.filename_to_uri (self.projectDir+"/"+self.listStore[path][m.DATE]+"/final.webm", None)

            Gio.AppInfo.launch_default_for_uri (uri, None)


    def buttons_x_offset (self, col, cat):
        (a,b) = self.recordButton.get_preferred_width ()
        #margin from the edge of the record button minus the padding
        self.encodeButton.set_margin_left (col.get_x_offset ()-a-10)

    def export_toggled (self, widget, path):
        self.listStore[path][m.EXPORT] = not self.listStore[path][m.EXPORT]
        #Don't allow export and delete to both be toggled
        self.listStore[path][m.DELETE] = False
        print ("export doggled")

    def delete_toggled (self, widget, path):
        self.listStore[path][m.DELETE] = not self.listStore[path][m.DELETE]
        #Don't allow export and delete to both be toggled
        self.listStore[path][m.EXPORT] = False
        print ("delete toggled")

    def enable_buttons (self):
        self.recordButton.set_sensitive (True)
        self.encodeButton.set_sensitive (True)
        self.recordingDeleteButton.set_sensitive (True)


    def open_file_chooser (self, menuitem, window):
        dialog = Gtk.FileChooserDialog ("Open File",
                                        None,
                                        Gtk.FileChooserAction.OPEN,
                                        (Gtk.STOCK_CANCEL,
                                        Gtk.ResponseType.CANCEL,
                                        Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        fileFilter = Gtk.FileFilter ()
        fileFilter.set_name ("Dawati User testing project")
        fileFilter.add_pattern ("*.dut")
#        fileFilter.add_mime_type("text/plain")
        dialog.add_filter (fileFilter)

        response = dialog.run ()

        if response == Gtk.ResponseType.OK:
            projectFile = dialog.get_filename ()
            self.projectDir = GLib.path_get_dirname (projectFile)
            self.listStore.clear ()
            self.projectConfig = dutProject.dutProject (projectFile, None)
            self.projectConfig.populate (self, m)

            self.enable_buttons ()

        dialog.destroy()


    def new_folder_chooser (self, menuitem, window):
        dialog = Gtk.FileChooserDialog ("New project",
                                        None,
                                        Gtk.FileChooserAction.CREATE_FOLDER,
                                        (Gtk.STOCK_CANCEL,
                                        Gtk.ResponseType.CANCEL,
                                        Gtk.STOCK_SAVE, Gtk.ResponseType.OK))

        dialog.set_do_overwrite_confirmation (True)


        response = dialog.run ()

        if response == Gtk.ResponseType.OK:
            self.listStore.clear ()
            self.projectDir = dialog.get_filename ()
            projectName = GLib.filename_display_basename (self.projectDir)
            self.projectConfig = dutProject.dutProject (self.projectDir+"/"+projectName+".dut", projectName)

            self.projectLabel.set_text ("Project: "+projectName)
            self.enable_buttons ()

        dialog.destroy()

    def on_mainWindow_destroy(self, widget):
        if self.projectConfig != None:
            self.projectConfig.dump (self, m)

        Gtk.main_quit()

    def update_progress_bar (self, encodeItem):
        percentDone = self.mux.pipe_report ()

        self.listStore.set_value (encodeItem, m.PROGRESS, percentDone)

        if percentDone == 100:
            name = self.listStore.get_value (encodeItem, m.TITLE)
            self.notification ("Dawati user testing",
                               "Encoding of "+name+" done")
            if (self.encodeQueue != None):
                #Allow the system to settle down before starting next
                time.sleep (3)
                self.run_encode_queue ()
            return False

        return True

    def create_new_dir (self, timeStamp):
        recordingDir = self.projectDir
        recordingDir += "/"+timeStamp+"/"
        GLib.mkdir_with_parents (recordingDir, 0755)
        return recordingDir

    # When the current item reaches 100% encoded it calls this again to see if
    # there are anymore to encode
    def run_encode_queue (self):
        if len (self.encodeQueue) > 0:
            encodeItem = self.encodeQueue.pop ()
        else:
            return

        print ("run encode queue")
        #If we've already encoded this item skip it
        if (self.listStore.get_value (encodeItem, m.PROGRESS) == 100):
            return

        recordingDir = self.projectDir+"/"+self.listStore.get_value (encodeItem, m.DATE)
        self.mux = dutMux.Muxer (recordingDir)
        GLib.timeout_add (500, self.update_progress_bar, encodeItem)
        print ("run muxer")
        self.mux.record (1)


    def encode_button_clicked_cb (self, button):

        listItr = self.listStore.get_iter_first ()

        while (listItr != None):
            print (self.listStore.get_value (listItr, m.EXPORT))
            print (self.listStore.get_value (listItr, m.TITLE))

            if (self.listStore.get_value (listItr, m.EXPORT) == True):
                #Add item to queue
                print ("Add " + self.listStore.get_value (listItr,
                                                          m.TITLE) + " to enqueue")
                self.encodeQueue.append (listItr)

            listItr = self.listStore.iter_next (listItr)

        if (self.encodeQueue != None):
            self.run_encode_queue ()


    def delete_button_clicked_cb (self, button):

        listItr = self.listStore.get_iter_first ()

        while (listItr != None):

            if (self.listStore.get_value (listItr, m.DELETE) == True):

                recName = self.listStore.get_value (listItr, m.TITLE)
                recDate = self.listStore.get_value (listItr, m.DATE)

                dialog = Gtk.MessageDialog(self.mainWindow,
                                           0, Gtk.MessageType.WARNING,
                                           Gtk.ButtonsType.OK_CANCEL,
                                           "Move '"+recName+"' to trash?")
                dialog.format_secondary_text(
                    "This operation cannot be undone.")
                response = dialog.run()
                if response == Gtk.ResponseType.OK:
                    shutil.move (self.projectDir+"/"+recDate, GLib.get_home_dir
                                 ()+"/.local/share/Trash/files/")
                    # Remove moves the current iter and True if it has moved
                    # onto the next item false if not
                    dialog.destroy ()

                    if (self.listStore.remove (listItr) == True):
                        continue
                    else:
                        listItr = None
                        continue

                dialog.destroy ()

            listItr = self.listStore.iter_next (listItr)


    def new_record_button_clicked_cb (self, button):
         # Open dialog for recording settings

         newRecording = dutNewRecording.NewRecording (self.mainWindow)

         recordingInfo = newRecording.get_new_recording_info ()

         if recordingInfo:

             self.listItr = self.listStore.append ([recordingInfo[0], #title
                                                    recordingInfo[1], #date
                                                    0, #duration
                                                    False, False, 0])

             self.mainWindow.iconify ()
             self.icon.set_visible (True)

             # Create a dir for this recording
             recordingDir = self.create_new_dir (recordingInfo[1])
             self.webcam = dutWebcamRecord.Webcam (recordingDir,
                                                   recordingInfo[2])
             self.screencast = dutScreencastRecord.Screencast (recordingDir)

             self.webcam.record (1)
             self.screencast.record (1)

    def stop_record (self, button):
        self.webcam.record (0)
        self.screencast.record (0)
        duration = self.webcam.get_duration ()

        #duration to seconds
        duration = round ((duration*0.000000001))
        print (duration)

        self.listStore.set_value (self.listItr, m.DURATION, int (duration))


        self.webcam = None
        self.screencast = None

        #Show the window again
        self.mainWindow.deiconify ()
        self.mainWindow.present ()
        self.icon.set_visible (False)


if __name__ == "__main__":
    dutMain()
    Gtk.main()
