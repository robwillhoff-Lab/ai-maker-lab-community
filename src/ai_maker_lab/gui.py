"""GTK 3 development dashboard; original implementation under MIT."""
import subprocess
import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
from .core import SetupError, launch_plan


class Dashboard(Gtk.Window):
    def __init__(self, config, workspace, launch_external=False):
        super().__init__(title='AI Maker Lab — ' + config['display_name'])
        self.config, self.workspace = config, workspace
        self.launch_external = launch_external
        self.children = []
        self.set_default_size(760, 560)
        self.connect('destroy', Gtk.main_quit)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(24)
        self.add(box)
        box.pack_start(Gtk.Label(label='AI Maker Lab'), False, False, 0)
        box.pack_start(Gtk.Label(label='Imagine → Predict → Build → Test → Explain'), False, False, 0)
        grid = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)
        box.pack_start(grid, True, True, 0)
        actions = [('Maker Coach', 'coach'), ('Code Lab', 'code'),
                   ('3D Workshop', 'bambu'), ('Gaming Lab', 'gaming'),
                   ('My Projects', 'projects'), ('Maker Journal', 'journal')]
        for i, (title, activity) in enumerate(actions):
            button = Gtk.Button(label=title)
            button.connect('clicked', lambda _, a=activity: self.perform(a))
            grid.attach(button, i % 2, i // 2, 1, 1)
        self.status = Gtk.Label(label='Development preview: external applications will not open.'
                                if not launch_external else 'External application launching enabled.')
        self.status.set_line_wrap(True)
        box.pack_start(self.status, False, False, 0)

    def perform(self, activity):
        try:
            if activity == 'journal':
                self.journal()
                return
            if activity == 'gaming':
                dialog = Gtk.Dialog(title='Gaming Lab', transient_for=self, modal=True)
                dialog.add_button('Cancel', Gtk.ResponseType.CANCEL)
                dialog.add_button('Minecraft', 1)
                dialog.add_button('Freedoom', 2)
                response = dialog.run()
                dialog.destroy()
                if response not in (1, 2):
                    return
                activity = 'minecraft' if response == 1 else 'freedoom'
            argv, cwd = launch_plan(activity, self.config, self.workspace)
            if not self.launch_external:
                self.status.set_text('Ready to open ' + activity + '. Preview mode keeps external apps closed.')
                return
            self.children = [child for child in self.children if child.poll() is None]
            process = subprocess.Popen(argv, cwd=cwd, shell=False,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.children.append(process)
            self.status.set_text('Launch requested: ' + activity + '. Check the application window.')
        except (OSError, SetupError) as error:
            self.status.set_text(str(error))

    def save_journal_edit(self, text, original):
        """Report success only after storage commits; failed edits remain open."""
        try:
            self.workspace.save_journal(text, expected=original)
        except (OSError, SetupError) as error:
            self.status.set_text('Journal not saved. ' + str(error) +
                                 ' Your edits remain open; retry or copy them before closing.')
            return False
        self.status.set_text('Journal saved in your workspace.')
        return True

    def journal(self):
        original = self.workspace.read_journal()
        dialog = Gtk.Dialog(title='Maker Journal', transient_for=self, modal=True)
        dialog.set_default_size(620, 440)
        dialog.add_button('Close', Gtk.ResponseType.CANCEL)
        dialog.add_button('Save', Gtk.ResponseType.OK)
        view = Gtk.TextView()
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        buffer = view.get_buffer()
        buffer.set_text(original)
        scroll = Gtk.ScrolledWindow()
        scroll.add(view)
        dialog.get_content_area().pack_start(scroll, True, True, 0)
        feedback = Gtk.Label(label='')
        feedback.set_line_wrap(True)
        dialog.get_content_area().pack_start(feedback, False, False, 0)
        dialog.show_all()
        while dialog.run() == Gtk.ResponseType.OK:
            text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
            if self.save_journal_edit(text, original):
                original = text
                feedback.set_text('Journal saved.')
            else:
                feedback.set_text(self.status.get_text())
        dialog.destroy()
