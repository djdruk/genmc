# genmc - Display Hex-Rays Microcode
#
# Requires IDA and decompiler(s) >= 7.3
#
# Based on code/ideas from:
# - vds13.py from Hexrays SDK
# - https://github.com/RolfRolles/HexRaysDeob
# - https://github.com/NeatMonster/MCExplorer

__author__ = "Dennis Elser"

# -----------------------------------------------------------------------------
import os, shutil, errno

import ida_idaapi
import ida_bytes
import ida_range
import ida_kernwin as kw
import ida_hexrays as hr
import ida_funcs
import ida_diskio
import ida_ida

# -----------------------------------------------------------------------------
def is_plugin():
    """returns True if this script is executed from within an IDA plugins
    directory, False otherwise."""
    return "__plugins__" in __name__

# -----------------------------------------------------------------------------
def get_target_dir():
    """returns destination path for plugin installation."""
    base = os.path.join(
        ida_diskio.get_user_idadir(),
        "plugins")
    return os.path.join(base, genmc.wanted_name+".py")

# -----------------------------------------------------------------------------
def is_installed():
    """checks whether script is present in designated plugins directory."""
    return os.path.isfile(get_target_dir())

# -----------------------------------------------------------------------------
SELF = __file__
def install_plugin():
    """Installs script to IDA userdir as a plugin."""
    if is_plugin():
        kw.msg("Command not available. Plugin already installed.\n")
        return False

    src = SELF
    if is_installed():
        btnid = kw.ask_yn(kw.ASKBTN_NO, "File exists. Replace?")
        if btnid is not kw.ASKBTN_YES:
            return False
    dst = get_target_dir()
    usrdir = os.path.dirname(dst)
    kw.msg("Copying script from \"%s\" to \"%s\" ..." % (src, usrdir))
    if not os.path.exists(usrdir):
        try:
            os.path.makedirs(usrdir)
        except OSError as e:
            if e.errno != errno.EEXIST:
                kw.msg("failed (mkdir)!\n")
                return False
    try:
        shutil.copy(src, dst)
    except:
        kw.msg("failed (copy)!\n")
        return False
    kw.msg("done!\n")
    return True

# -----------------------------------------------------------------------------
def is_ida_version(requested):
    """Checks minimum required IDA version."""
    rv = requested.split(".")
    kv = kw.get_kernel_version().split(".")

    count = min(len(rv), len(kv))
    if not count:
        return False

    for i in xrange(count):
        if int(kv[i]) < int(rv[i]):
            return False
    return True

# -----------------------------------------------------------------------------
def is_compatible():
    """Checks whether script is compatible with current IDA and
    decompiler versions."""
    min_ida_ver = "7.3"
    return is_ida_version(min_ida_ver) and hr.init_hexrays_plugin()

# -----------------------------------------------------------------------------
class printer_t(hr.vd_printer_t):
    """Converts microcode output to an array of strings."""
    def __init__(self, *args):
        hr.vd_printer_t.__init__(self)
        self.mc = []

    def get_mc(self):
        return self.mc

    def _print(self, indent, line):
        self.mc.append(line)
        return 1

# -----------------------------------------------------------------------------
class microcode_viewer_t(kw.simplecustviewer_t):
    """Creates a widget that displays Hex-Rays microcode."""
    def Create(self, title, lines = []):
        title = "Microcode: %s" % title
        if not kw.simplecustviewer_t.Create(self, title):
            return False

        for line in lines:
            self.AddLine(line)
        return True

# -----------------------------------------------------------------------------
def ask_desired_maturity():
    """Displays a dialog which lets the user choose a maturity level
    of the microcode to generate."""
    maturity_levels = [
    ["MMAT_GENERATED", hr.MMAT_GENERATED],
    ["MMAT_PREOPTIMIZED", hr.MMAT_PREOPTIMIZED],
    ["MMAT_LOCOPT", hr.MMAT_LOCOPT],
    ["MMAT_CALLS", hr.MMAT_CALLS],
    ["MMAT_GLBOPT1", hr.MMAT_GLBOPT1],
    ["MMAT_GLBOPT2", hr.MMAT_GLBOPT2],
    ["MMAT_GLBOPT3", hr.MMAT_GLBOPT3],
    ["MMAT_LVARS", hr.MMAT_LVARS]]

    class MaturityForm(kw.Form):
        def __init__(self):
            form = """%s
             <Maturity level:{mat_lvl}>\n\n\n
             <##MBA Flags##MBA_SHORT:{flags_short}>{chkgroup_flags}>
             """ % genmc.wanted_name

            dropdown_ctl = kw.Form.DropdownListControl(
                [text for text, _ in maturity_levels])
            chk_ctl = kw.Form.ChkGroupControl(("flags_short",))

            controls = {"mat_lvl": dropdown_ctl,
            "chkgroup_flags": chk_ctl}

            kw.Form.__init__(self, form, controls)

    form = MaturityForm()
    form, args = form.Compile()
    ok = form.Execute()
    mmat = None
    text = None
    flags = 0
    if ok == 1:
        text, mmat = maturity_levels[form.mat_lvl.value]
    flags |= hr.MBA_SHORT if form.flags_short.checked else 0
    form.Free()
    return (text, mmat, flags)

# -----------------------------------------------------------------------------
def show_microcode():
    """Generates and displays microcode for an address range.
    An address range can be a selection of code or that of
    the current function."""
    sel, sea, eea = kw.read_range_selection(None)
    pfn = ida_funcs.get_func(kw.get_screen_ea())
    if not sel and not pfn:
        return (False, "Position cursor within a function or select range")

    if not sel and pfn:
        sea = pfn.start_ea
        eea = pfn.end_ea

    addr_fmt = "%016x" if ida_ida.inf_is_64bit() else "%08x"
    F = ida_bytes.get_flags(sea)
    if not ida_bytes.is_code(F):
        return (False, "The selected range must start with an instruction")

    text, mmat, mba_flags = ask_desired_maturity()
    if text is None and mmat is None:
        return (True, "Cancelled")

    hf = hr.hexrays_failure_t()
    mbr = hr.mba_ranges_t()
    mbr.ranges.push_back(ida_range.range_t(sea, eea))
    ml = hr.mlist_t()
    mba = hr.gen_microcode(mbr, hf, ml, hr.DECOMP_WARNINGS, mmat)
    if not mba:
        return (False, "0x%s: %s" % (addr_fmt % hf.errea, hf.str))

    vp = printer_t()
    mba.set_mba_flags(mba_flags)
    mba._print(vp)
    mcv = microcode_viewer_t()
    if not mcv.Create("0x%s-0x%s (%s)" % (addr_fmt % sea, addr_fmt % eea, text), vp.get_mc()):
        return (False, "Error creating viewer")

    mcv.Show()
    return (True,
        "Successfully generated microcode for 0x%s..0x%s" % (addr_fmt % sea, addr_fmt % eea))

# -----------------------------------------------------------------------------
def create_mc_widget():
    """Checks minimum requirements for the script/plugin to be able to run.
    Displays microcode or in case of failure, displays error message.
    This function acts as the main entry point that is invoked if the
    code is run as a script or as a plugin."""
    if not is_compatible():
        kw.msg("%s: Unsupported IDA / Hex-rays version\n" % (genmc.wanted_name))
        return False
    success, message = show_microcode()
    output = kw.msg if success else kw.warning
    output("%s: %s\n" % (genmc.wanted_name, message))
    return success

# -----------------------------------------------------------------------------
class genmc(ida_idaapi.plugin_t):
    """Class that is required for the code to be recognized as
    a plugin by IDA."""
    flags = 0
    comment = "Display microcode"
    help = comment
    wanted_name = 'genmc'
    wanted_hotkey = 'Ctrl-Shift-M'

    def init(self):
        return (ida_idaapi.PLUGIN_OK if
            is_compatible() else ida_idaapi.PLUGIN_SKIP)

    def run(self, arg):
        create_mc_widget()

    def term(self):
        pass

# -----------------------------------------------------------------------------
def PLUGIN_ENTRY():
    """Entry point of this code if launched as a plugin."""
    return genmc()

# -----------------------------------------------------------------------------
def SCRIPT_ENTRY():
    """Entry point of this code if launched as a script."""
    if not is_plugin():
        if not is_installed():
            kw.msg(("%s: Available commands:\n"
                "[+] \"install_plugin()\" - install script to ida_userdir/plugins\n") % (
                genmc.wanted_name))
        create_mc_widget()
        return True
    return False

# -----------------------------------------------------------------------------
SCRIPT_ENTRY()