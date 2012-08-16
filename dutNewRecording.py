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

import gst
import time

from datetime import datetime

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkX11
from gi.repository import GUdev
Gdk.threads_init ()

class mode:
    TWOCAM, SCREENCAST = range (2)

class NewRecording:
    def __init__(self, mainWindow):

        self.player = None
        self.busSig1 = None
        self.busSig2 = None
        self.recordingTitle = None
        self.secondaryDevice = "/dev/video0" #Default recording device
        self.primaryDevice = "Screen"

        self.dialog = Gtk.Dialog ("Create recoding",
                                  mainWindow,
                                  2)

        cancel = self.dialog.add_button ("Cancel", Gtk.ResponseType.CANCEL)
        accept = self.dialog.add_button ("Start recording", Gtk.ResponseType.ACCEPT)

        # UI Elements for create recording dialog
        label = Gtk.Label (label="Recording name:", halign=Gtk.Align.START)
        entry = Gtk.Entry ()
        primaryCapture = Gtk.ComboBoxText ()
        primaryCapture.connect ("changed", self.primary_capture_changed)
        primaryCapture.set_title ("Primary Capture")
        primaryCapture.append_text ("Screen")
        primaryCaptureLabel = Gtk.Label ("Primary capture:")

        secondaryCapture = Gtk.ComboBoxText ()
        secondaryCapture.connect ("changed", self.secondary_capture_changed)
        secondaryCapture.set_title ("Secondary Capture")

        #Add available video4linux devices
        devices = GUdev.Client ().query_by_subsystem ("video4linux")


        for device in devices:
            secondaryCapture.append_text (device.get_name ())
            primaryCapture.append_text (device.get_name ())

        secondaryCaptureLabel = Gtk.Label ("Secondary capture:")

        devicesBox = Gtk.HBox ()
        devicesBox.pack_start (primaryCaptureLabel, False, False, 3)
        devicesBox.pack_start (primaryCapture, False, False, 3)
        devicesBox.pack_start (secondaryCaptureLabel, False, False, 3)
        devicesBox.pack_start (secondaryCapture, False, False, 3)

        self.playerWindow = Gtk.DrawingArea ()
        self.playerWindow.set_double_buffered (False)
        self.playerWindow.set_size_request (600, 300)
        self.playerWindow.connect ("realize", self.window_real)


        audioToggle = Gtk.Switch ()
        audioSource = Gtk.ComboBoxText ()


        audioBox = Gtk.HBox ()


        contentArea = self.dialog.get_content_area ()
        contentArea.set_spacing (8)
        contentArea.add (label)
        contentArea.add (entry)
        contentArea.add (devicesBox)
        contentArea.add (self.playerWindow)
        contentArea.add (audioBox)

        contentArea.show_all ()

        #Main loop
        self.response = self.dialog.run ()

        self.recordingTitle = entry.get_text ()


        self.player.set_state (gst.STATE_NULL)
        self.player.get_bus ().disconnect (self.busSig1)
        self.player.get_bus ().disconnect (self.busSig2)
        self.player = None
        self.dialog.destroy ()

    #TODO make sure you can't select e.g. video0 primary and video0 secondary
    def secondary_capture_changed (self, combo):
        print ("secondary changed")
        deviceName = combo.get_active_text ()
        self.secondaryDevice = "/dev/"+deviceName

        self.player.set_state (gst.STATE_READY)
        #Update the v4l element's device property

        v4l = self.player.get_by_name ("cam1")
        v4l.set_locked_state (False)
        v4l.set_state (gst.STATE_NULL)

        v4l.set_property ("device", self.secondaryDevice)

        self.player.set_state (gst.STATE_PLAYING)


    def primary_capture_changed (self, combo):
        deviceName = combo.get_active_text ()
        self.primaryDevice = "/dev/"+deviceName

        if (deviceName == "Screen"):
            self.video_preview_screencast_webcam ()
            return
        #If we're not running in two cam mode already set it up
        elif (self.mode != mode.TWOCAM):
            self.video_preview_webcam_webcam ()

        self.player.set_state (gst.STATE_READY)

        v4l = self.player.get_by_name ("cam2")
        v4l.set_locked_state (False)
        v4l.set_state (gst.STATE_NULL)

        #Update the v4l element's device property
        v4l.set_property ("device", self.secondaryDevice)
        self.player.set_state (gst.STATE_PLAYING)


    def window_real (self,wef2):
        print ("drawable realised")
        self.video_preview_screencast_webcam ()

    def video_preview_screencast_webcam (self):

        if (self.player):
            self.player.set_state(gst.STATE_NULL)

        self.mode = mode.SCREENCAST

        screen = Gdk.get_default_root_window ().get_display ().get_screen (0)
        posY = str (screen.get_height () - 240)
        posX = str (screen.get_width () - 320)

        self.player = gst.parse_launch ("""v4l2src device=/dev/video0 name="cam1" !
                                       videoscale ! queue ! videoflip
                                       method=horizontal-flip !
                                       video/x-raw-yuv,height=240,framerate=15/1
                                       ! videomixer name=mix sink_0::xpos=0
                                       sink_0::ypos=0 sink_1::xpos="""+posX+"""
                                       sink_1::ypos="""+posY+""" !
                                       xvimagesink  sync=false       ximagesrc
                                       use-damage=false show-pointer=true  !
                                       videoscale ! video/x-raw-rgb,framerate=15/1 ! ffmpegcolorspace ! video/x-raw-yuv ! mix.""")


        self.player.set_state(gst.STATE_PLAYING)

        bus = self.player.get_bus()
        bus.add_signal_watch()
        bus.enable_sync_message_emission()
        self.busSig1 = bus.connect("message", self.on_message)
        self.busSig2 = bus.connect("sync-message::element",
                                   self.on_sync_message)

    def video_preview_webcam_webcam (self):

        self.mode = mode.TWOCAM

        if (self.player):
            self.player.set_state(gst.STATE_NULL)

        posY =str (0)
        posX = str (0)

        self.player = gst.parse_launch ("""v4l2src device=/dev/video0 name="cam1" !
                                       videoscale ! queue ! videoflip
                                       method=horizontal-flip !
                                       video/x-raw-yuv,height=240,framerate=15/1
                                       ! videomixer name=mix sink_0::xpos=0
                                       sink_0::ypos=0 sink_1::xpos="""+posX+"""
                                       sink_1::ypos="""+posY+""" !
                                       xvimagesink  sync=false
                                       v4l2src device=/dev/video1 name="cam2" !
                                        videoscale ! queue ! videoflip
                                        method=horizontal-flip !
                                        video/x-raw-yuv ! mix.""")


        self.player.set_state(gst.STATE_PLAYING)

        bus = self.player.get_bus()
        bus.add_signal_watch()
        bus.enable_sync_message_emission()
        self.busSig1 = bus.connect("message", self.on_message)
        self.busSig2 = bus.connect("sync-message::element",
                                   self.on_sync_message)


    def on_message(self, bus, message):
        t = message.type
        if t == gst.MESSAGE_EOS:
            self.player.set_state(gst.STATE_NULL)
        elif t == gst.MESSAGE_ERROR:
            self.player.set_state(gst.STATE_NULL)
            err, debug = message.parse_error()
            print "Error: %s" % err, debug

    def on_sync_message(self, bus, message):
        if message.structure is None:
            return
        message_name = message.structure.get_name()
        if message_name == "prepare-xwindow-id":
            imagesink = message.src

            Gdk.threads_enter()

            # Sync with the X server before giving the X-id to the sink
            Gdk.get_default_root_window ().get_display ().sync ()
            xid = self.playerWindow.get_window ().get_xid()
            imagesink.set_property("force-aspect-ratio", True)
            imagesink.set_xwindow_id (xid)

            Gdk.threads_leave ()

    def get_new_recording_info (self):
        if self.response == Gtk.ResponseType.ACCEPT:
            #TODO DONT USE timedate in folder structure
            timeStamp = datetime.today().strftime("%d-%m-%H%M%S")
            #TODO also return the result of video source combos
            print (self.recordingTitle)
            info = ([self.recordingTitle, timeStamp, self.secondaryDevice])
            return info
        else:
            return None









