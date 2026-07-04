// EQ Mod Manager launcher: starts the bundled Python runtime with the
// GUI script, no console window. Compiled with the .NET Framework csc
// that ships in every Windows installation.
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

static class Launcher
{
    [STAThread]
    static void Main()
    {
        string here = AppDomain.CurrentDomain.BaseDirectory;
        string pyw = Path.Combine(here, "runtime", "pythonw.exe");
        string gui = Path.Combine(here, "manager", "eqtool_gui.py");
        if (!File.Exists(pyw) || !File.Exists(gui))
        {
            MessageBox.Show(
                "Missing files - re-extract the full zip.\n\n" +
                pyw + "\n" + gui,
                "EQ Mod Manager", MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return;
        }
        var psi = new ProcessStartInfo(pyw, "\"" + gui + "\"");
        psi.WorkingDirectory = Path.Combine(here, "manager");
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        Process.Start(psi);
    }
}
