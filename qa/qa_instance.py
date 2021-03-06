#
#

# Copyright (C) 2007, 2011, 2012, 2013 Google Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.


"""Instance related QA tests.

"""

import operator
import re

from ganeti import utils
from ganeti import constants
from ganeti import query
from ganeti import pathutils

import qa_config
import qa_utils
import qa_error

from qa_utils import AssertIn, AssertCommand, AssertEqual
from qa_utils import InstanceCheck, INST_DOWN, INST_UP, FIRST_ARG, RETURN_VALUE


def _GetDiskStatePath(disk):
  return "/sys/block/%s/device/state" % disk


def _GetGenericAddParameters(inst, force_mac=None):
  params = ["-B"]
  params.append("%s=%s,%s=%s" % (constants.BE_MINMEM,
                                 qa_config.get(constants.BE_MINMEM),
                                 constants.BE_MAXMEM,
                                 qa_config.get(constants.BE_MAXMEM)))
  for idx, size in enumerate(qa_config.get("disk")):
    params.extend(["--disk", "%s:size=%s" % (idx, size)])

  # Set static MAC address if configured
  if force_mac:
    nic0_mac = force_mac
  else:
    nic0_mac = inst.GetNicMacAddr(0, None)

  if nic0_mac:
    params.extend(["--net", "0:mac=%s" % nic0_mac])

  return params


def _DiskTest(node, disk_template):
  instance = qa_config.AcquireInstance()
  try:
    cmd = (["gnt-instance", "add",
            "--os-type=%s" % qa_config.get("os"),
            "--disk-template=%s" % disk_template,
            "--node=%s" % node] +
           _GetGenericAddParameters(instance))
    cmd.append(instance.name)

    AssertCommand(cmd)

    _CheckSsconfInstanceList(instance.name)
    instance.SetDiskTemplate(disk_template)

    return instance
  except:
    instance.Release()
    raise


def _GetInstanceInfo(instance):
  """Return information about the actual state of an instance.

  @type instance: string
  @param instance: the instance name
  @return: a dictionary with the following keys:
      - "nodes": instance nodes, a list of strings
      - "volumes": instance volume IDs, a list of strings
      - "drbd-minors": DRBD minors used by the instance, a dictionary where
        keys are nodes, and values are lists of integers (or an empty
        dictionary for non-DRBD instances)

  """
  master = qa_config.GetMasterNode()
  infocmd = utils.ShellQuoteArgs(["gnt-instance", "info", instance])
  info_out = qa_utils.GetCommandOutput(master.primary, infocmd)
  re_node = re.compile(r"^\s+-\s+(?:primary|secondaries):\s+(\S.+)$")
  node_elem = r"([^,()]+)(?:\s+\([^)]+\))?"
  # re_nodelist matches a list of nodes returned by gnt-instance info, e.g.:
  #  node1.fqdn
  #  node2.fqdn,node3.fqdn
  #  node4.fqdn (group mygroup, group UUID 01234567-abcd-0123-4567-0123456789ab)
  # FIXME This works with no more than 2 secondaries
  re_nodelist = re.compile(node_elem + "(?:," + node_elem + ")?$")
  re_vol = re.compile(r"^\s+logical_id:\s+(\S+)$")
  re_drbdnode = re.compile(r"^\s+node[AB]:\s+([^\s,]+),\s+minor=([0-9]+)$")
  nodes = []
  vols = []
  drbd_min = {}
  for line in info_out.splitlines():
    m = re_node.match(line)
    if m:
      nodestr = m.group(1)
      m2 = re_nodelist.match(nodestr)
      if m2:
        nodes.extend(filter(None, m2.groups()))
      else:
        nodes.append(nodestr)
    m = re_vol.match(line)
    if m:
      vols.append(m.group(1))
    m = re_drbdnode.match(line)
    if m:
      node = m.group(1)
      minor = int(m.group(2))
      if drbd_min.get(node) is not None:
        drbd_min[node].append(minor)
      else:
        drbd_min[node] = [minor]
  assert vols
  assert nodes
  return {"nodes": nodes, "volumes": vols, "drbd-minors": drbd_min}


def _DestroyInstanceVolumes(instance):
  """Remove all the LVM volumes of an instance.

  This is used to simulate HW errors (dead nodes, broken disks...); the
  configuration of the instance is not affected.
  @type instance: dictionary
  @param instance: the instance

  """
  info = _GetInstanceInfo(instance.name)
  vols = info["volumes"]
  for node in info["nodes"]:
    AssertCommand(["lvremove", "-f"] + vols, node=node)


def _GetBoolInstanceField(instance, field):
  """Get the Boolean value of a field of an instance.

  @type instance: string
  @param instance: Instance name
  @type field: string
  @param field: Name of the field

  """
  master = qa_config.GetMasterNode()
  infocmd = utils.ShellQuoteArgs(["gnt-instance", "list", "--no-headers",
                                  "-o", field, instance])
  info_out = qa_utils.GetCommandOutput(master.primary, infocmd).strip()
  if info_out == "Y":
    return True
  elif info_out == "N":
    return False
  else:
    raise qa_error.Error("Field %s of instance %s has a non-Boolean value:"
                         " %s" % (field, instance, info_out))


def IsFailoverSupported(instance):
  return instance.disk_template in constants.DTS_MIRRORED


def IsMigrationSupported(instance):
  return instance.disk_template in constants.DTS_MIRRORED


def IsDiskReplacingSupported(instance):
  return instance.disk_template == constants.DT_DRBD8


@InstanceCheck(None, INST_UP, RETURN_VALUE)
def TestInstanceAddWithPlainDisk(nodes):
  """gnt-instance add -t plain"""
  assert len(nodes) == 1
  return _DiskTest(nodes[0].primary, constants.DT_PLAIN)


@InstanceCheck(None, INST_UP, RETURN_VALUE)
def TestInstanceAddWithDrbdDisk(nodes):
  """gnt-instance add -t drbd"""
  assert len(nodes) == 2
  return _DiskTest(":".join(map(operator.attrgetter("primary"), nodes)),
                   constants.DT_DRBD8)


@InstanceCheck(None, INST_DOWN, FIRST_ARG)
def TestInstanceRemove(instance):
  """gnt-instance remove"""
  AssertCommand(["gnt-instance", "remove", "-f", instance.name])


@InstanceCheck(INST_DOWN, INST_UP, FIRST_ARG)
def TestInstanceStartup(instance):
  """gnt-instance startup"""
  AssertCommand(["gnt-instance", "startup", instance.name])


@InstanceCheck(INST_UP, INST_DOWN, FIRST_ARG)
def TestInstanceShutdown(instance):
  """gnt-instance shutdown"""
  AssertCommand(["gnt-instance", "shutdown", instance.name])


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceReboot(instance):
  """gnt-instance reboot"""
  options = qa_config.get("options", {})
  reboot_types = options.get("reboot-types", constants.REBOOT_TYPES)
  name = instance.name
  for rtype in reboot_types:
    AssertCommand(["gnt-instance", "reboot", "--type=%s" % rtype, name])

  AssertCommand(["gnt-instance", "shutdown", name])
  qa_utils.RunInstanceCheck(instance, False)
  AssertCommand(["gnt-instance", "reboot", name])

  master = qa_config.GetMasterNode()
  cmd = ["gnt-instance", "list", "--no-headers", "-o", "status", name]
  result_output = qa_utils.GetCommandOutput(master.primary,
                                            utils.ShellQuoteArgs(cmd))
  AssertEqual(result_output.strip(), constants.INSTST_RUNNING)


@InstanceCheck(INST_DOWN, INST_DOWN, FIRST_ARG)
def TestInstanceReinstall(instance):
  """gnt-instance reinstall"""
  AssertCommand(["gnt-instance", "reinstall", "-f", instance.name])

  # Test with non-existant OS definition
  AssertCommand(["gnt-instance", "reinstall", "-f",
                 "--os-type=NonExistantOsForQa",
                 instance.name],
                fail=True)


def _ReadSsconfInstanceList():
  """Reads ssconf_instance_list from the master node.

  """
  master = qa_config.GetMasterNode()

  cmd = ["cat", utils.PathJoin(pathutils.DATA_DIR,
                               "ssconf_%s" % constants.SS_INSTANCE_LIST)]

  return qa_utils.GetCommandOutput(master.primary,
                                   utils.ShellQuoteArgs(cmd)).splitlines()


def _CheckSsconfInstanceList(instance):
  """Checks if a certain instance is in the ssconf instance list.

  @type instance: string
  @param instance: Instance name

  """
  AssertIn(qa_utils.ResolveInstanceName(instance),
           _ReadSsconfInstanceList())


@InstanceCheck(INST_DOWN, INST_DOWN, FIRST_ARG)
def TestInstanceRenameAndBack(rename_source, rename_target):
  """gnt-instance rename

  This must leave the instance with the original name, not the target
  name.

  """
  _CheckSsconfInstanceList(rename_source)

  # first do a rename to a different actual name, expecting it to fail
  qa_utils.AddToEtcHosts(["meeeeh-not-exists", rename_target])
  try:
    AssertCommand(["gnt-instance", "rename", rename_source, rename_target],
                  fail=True)
    _CheckSsconfInstanceList(rename_source)
  finally:
    qa_utils.RemoveFromEtcHosts(["meeeeh-not-exists", rename_target])

  # Check instance volume tags correctly updated
  # FIXME: this is LVM specific!
  info = _GetInstanceInfo(rename_source)
  tags_cmd = ("lvs -o tags --noheadings %s | grep " %
              (" ".join(info["volumes"]), ))

  # and now rename instance to rename_target...
  AssertCommand(["gnt-instance", "rename", rename_source, rename_target])
  _CheckSsconfInstanceList(rename_target)
  qa_utils.RunInstanceCheck(rename_source, False)
  qa_utils.RunInstanceCheck(rename_target, False)

  # NOTE: tags might not be the exactly as the instance name, due to
  # charset restrictions; hence the test might be flaky
  if rename_source != rename_target:
    for node in info["nodes"]:
      AssertCommand(tags_cmd + rename_source, node=node, fail=True)
      AssertCommand(tags_cmd + rename_target, node=node, fail=False)

  # and back
  AssertCommand(["gnt-instance", "rename", rename_target, rename_source])
  _CheckSsconfInstanceList(rename_source)
  qa_utils.RunInstanceCheck(rename_target, False)

  if rename_source != rename_target:
    for node in info["nodes"]:
      AssertCommand(tags_cmd + rename_source, node=node, fail=False)
      AssertCommand(tags_cmd + rename_target, node=node, fail=True)


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceFailover(instance):
  """gnt-instance failover"""
  if not IsFailoverSupported(instance):
    print qa_utils.FormatInfo("Instance doesn't support failover, skipping"
                              " test")
    return

  cmd = ["gnt-instance", "failover", "--force", instance.name]

  # failover ...
  AssertCommand(cmd)
  qa_utils.RunInstanceCheck(instance, True)

  # ... and back
  AssertCommand(cmd)


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceMigrate(instance, toggle_always_failover=True):
  """gnt-instance migrate"""
  if not IsMigrationSupported(instance):
    print qa_utils.FormatInfo("Instance doesn't support migration, skipping"
                              " test")
    return

  cmd = ["gnt-instance", "migrate", "--force", instance.name]
  af_par = constants.BE_ALWAYS_FAILOVER
  af_field = "be/" + constants.BE_ALWAYS_FAILOVER
  af_init_val = _GetBoolInstanceField(instance.name, af_field)

  # migrate ...
  AssertCommand(cmd)
  # TODO: Verify the choice between failover and migration
  qa_utils.RunInstanceCheck(instance, True)

  # ... and back (possibly with always_failover toggled)
  if toggle_always_failover:
    AssertCommand(["gnt-instance", "modify", "-B",
                   ("%s=%s" % (af_par, not af_init_val)),
                   instance.name])
  AssertCommand(cmd)
  # TODO: Verify the choice between failover and migration
  qa_utils.RunInstanceCheck(instance, True)
  if toggle_always_failover:
    AssertCommand(["gnt-instance", "modify", "-B",
                   ("%s=%s" % (af_par, af_init_val)), instance.name])

  # TODO: Split into multiple tests
  AssertCommand(["gnt-instance", "shutdown", instance.name])
  qa_utils.RunInstanceCheck(instance, False)
  AssertCommand(cmd, fail=True)
  AssertCommand(["gnt-instance", "migrate", "--force", "--allow-failover",
                 instance.name])
  AssertCommand(["gnt-instance", "start", instance.name])
  AssertCommand(cmd)
  # @InstanceCheck enforces the check that the instance is running
  qa_utils.RunInstanceCheck(instance, True)

  AssertCommand(["gnt-instance", "modify", "-B",
                 ("%s=%s" %
                  (constants.BE_ALWAYS_FAILOVER, constants.VALUE_TRUE)),
                 instance.name])

  AssertCommand(cmd)
  qa_utils.RunInstanceCheck(instance, True)
  # TODO: Verify that a failover has been done instead of a migration

  # TODO: Verify whether the default value is restored here (not hardcoded)
  AssertCommand(["gnt-instance", "modify", "-B",
                 ("%s=%s" %
                  (constants.BE_ALWAYS_FAILOVER, constants.VALUE_FALSE)),
                 instance.name])

  AssertCommand(cmd)
  qa_utils.RunInstanceCheck(instance, True)


def TestInstanceInfo(instance):
  """gnt-instance info"""
  AssertCommand(["gnt-instance", "info", instance.name])


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceModify(instance):
  """gnt-instance modify"""
  default_hv = qa_config.GetDefaultHypervisor()

  # Assume /sbin/init exists on all systems
  test_kernel = "/sbin/init"
  test_initrd = test_kernel

  orig_maxmem = qa_config.get(constants.BE_MAXMEM)
  orig_minmem = qa_config.get(constants.BE_MINMEM)
  #orig_bridge = qa_config.get("bridge", "xen-br0")

  args = [
    ["-B", "%s=128" % constants.BE_MINMEM],
    ["-B", "%s=128" % constants.BE_MAXMEM],
    ["-B", "%s=%s,%s=%s" % (constants.BE_MINMEM, orig_minmem,
                            constants.BE_MAXMEM, orig_maxmem)],
    ["-B", "%s=2" % constants.BE_VCPUS],
    ["-B", "%s=1" % constants.BE_VCPUS],
    ["-B", "%s=%s" % (constants.BE_VCPUS, constants.VALUE_DEFAULT)],
    ["-B", "%s=%s" % (constants.BE_ALWAYS_FAILOVER, constants.VALUE_TRUE)],
    ["-B", "%s=%s" % (constants.BE_ALWAYS_FAILOVER, constants.VALUE_DEFAULT)],

    ["-H", "%s=%s" % (constants.HV_KERNEL_PATH, test_kernel)],
    ["-H", "%s=%s" % (constants.HV_KERNEL_PATH, constants.VALUE_DEFAULT)],

    # TODO: bridge tests
    #["--bridge", "xen-br1"],
    #["--bridge", orig_bridge],
    ]

  if default_hv == constants.HT_XEN_PVM:
    args.extend([
      ["-H", "%s=%s" % (constants.HV_INITRD_PATH, test_initrd)],
      ["-H", "no_%s" % (constants.HV_INITRD_PATH, )],
      ["-H", "%s=%s" % (constants.HV_INITRD_PATH, constants.VALUE_DEFAULT)],
      ])
  elif default_hv == constants.HT_XEN_HVM:
    args.extend([
      ["-H", "%s=acn" % constants.HV_BOOT_ORDER],
      ["-H", "%s=%s" % (constants.HV_BOOT_ORDER, constants.VALUE_DEFAULT)],
      ])

  for alist in args:
    AssertCommand(["gnt-instance", "modify"] + alist + [instance.name])

  # check no-modify
  AssertCommand(["gnt-instance", "modify", instance.name], fail=True)

  # Marking offline while instance is running must fail...
  AssertCommand(["gnt-instance", "modify", "--offline", instance.name],
                 fail=True)

  # ...while making it online is ok, and should work
  AssertCommand(["gnt-instance", "modify", "--online", instance.name])


@InstanceCheck(INST_DOWN, INST_DOWN, FIRST_ARG)
def TestInstanceStoppedModify(instance):
  """gnt-instance modify (stopped instance)"""
  name = instance.name

  # Instance was not marked offline; try marking it online once more
  AssertCommand(["gnt-instance", "modify", "--online", name])

  # Mark instance as offline
  AssertCommand(["gnt-instance", "modify", "--offline", name])

  # When the instance is offline shutdown should only work with --force,
  # while start should never work
  AssertCommand(["gnt-instance", "shutdown", name], fail=True)
  AssertCommand(["gnt-instance", "shutdown", "--force", name])
  AssertCommand(["gnt-instance", "start", name], fail=True)
  AssertCommand(["gnt-instance", "start", "--force", name], fail=True)

  # Also do offline to offline
  AssertCommand(["gnt-instance", "modify", "--offline", name])

  # And online again
  AssertCommand(["gnt-instance", "modify", "--online", name])


@InstanceCheck(INST_DOWN, INST_DOWN, FIRST_ARG)
def TestInstanceConvertDiskToPlain(instance, inodes):
  """gnt-instance modify -t"""
  name = instance.name

  template = instance.disk_template
  if template != constants.DT_DRBD8:
    print qa_utils.FormatInfo("Unsupported template %s, skipping conversion"
                              " test" % template)
    return

  assert len(inodes) == 2
  AssertCommand(["gnt-instance", "modify", "-t", constants.DT_PLAIN, name])
  AssertCommand(["gnt-instance", "modify", "-t", constants.DT_DRBD8,
                 "-n", inodes[1].primary, name])


@InstanceCheck(INST_DOWN, INST_DOWN, FIRST_ARG)
def TestInstanceGrowDisk(instance):
  """gnt-instance grow-disk"""
  if qa_config.GetExclusiveStorage():
    print qa_utils.FormatInfo("Test not supported with exclusive_storage")
    return
  name = instance.name
  all_size = qa_config.get("disk")
  all_grow = qa_config.get("disk-growth")
  if not all_grow:
    # missing disk sizes but instance grow disk has been enabled,
    # let's set fixed/nomimal growth
    all_grow = ["128M" for _ in all_size]
  for idx, (size, grow) in enumerate(zip(all_size, all_grow)):
    # succeed in grow by amount
    AssertCommand(["gnt-instance", "grow-disk", name, str(idx), grow])
    # fail in grow to the old size
    AssertCommand(["gnt-instance", "grow-disk", "--absolute", name, str(idx),
                   size], fail=True)
    # succeed to grow to old size + 2 * growth
    int_size = utils.ParseUnit(size)
    int_grow = utils.ParseUnit(grow)
    AssertCommand(["gnt-instance", "grow-disk", "--absolute", name, str(idx),
                   str(int_size + 2 * int_grow)])


def TestInstanceList():
  """gnt-instance list"""
  qa_utils.GenericQueryTest("gnt-instance", query.INSTANCE_FIELDS.keys())


def TestInstanceListFields():
  """gnt-instance list-fields"""
  qa_utils.GenericQueryFieldsTest("gnt-instance", query.INSTANCE_FIELDS.keys())


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceConsole(instance):
  """gnt-instance console"""
  AssertCommand(["gnt-instance", "console", "--show-cmd", instance.name])


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestReplaceDisks(instance, curr_nodes, other_nodes):
  """gnt-instance replace-disks"""
  def buildcmd(args):
    cmd = ["gnt-instance", "replace-disks"]
    cmd.extend(args)
    cmd.append(instance.name)
    return cmd

  if not IsDiskReplacingSupported(instance):
    print qa_utils.FormatInfo("Instance doesn't support disk replacing,"
                              " skipping test")
    return

  # Currently all supported templates have one primary and one secondary node
  assert len(curr_nodes) == 2
  snode = curr_nodes[1]
  assert len(other_nodes) == 1
  othernode = other_nodes[0]

  options = qa_config.get("options", {})
  use_ialloc = options.get("use-iallocators", True)
  for data in [
    ["-p"],
    ["-s"],
    # A placeholder; the actual command choice depends on use_ialloc
    None,
    # Restore the original secondary
    ["--new-secondary=%s" % snode.primary],
    ]:
    if data is None:
      if use_ialloc:
        data = ["-I", constants.DEFAULT_IALLOCATOR_SHORTCUT]
      else:
        data = ["--new-secondary=%s" % othernode.primary]
    AssertCommand(buildcmd(data))

  AssertCommand(buildcmd(["-a"]))
  AssertCommand(["gnt-instance", "stop", instance.name])
  AssertCommand(buildcmd(["-a"]), fail=True)
  AssertCommand(["gnt-instance", "activate-disks", instance.name])
  AssertCommand(["gnt-instance", "activate-disks", "--wait-for-sync",
                 instance.name])
  AssertCommand(buildcmd(["-a"]))
  AssertCommand(["gnt-instance", "start", instance.name])


def _AssertRecreateDisks(cmdargs, instance, fail=False, check=True,
                         destroy=True):
  """Execute gnt-instance recreate-disks and check the result

  @param cmdargs: Arguments (instance name excluded)
  @param instance: Instance to operate on
  @param fail: True if the command is expected to fail
  @param check: If True and fail is False, check that the disks work
  @prama destroy: If True, destroy the old disks first

  """
  if destroy:
    _DestroyInstanceVolumes(instance)
  AssertCommand((["gnt-instance", "recreate-disks"] + cmdargs +
                 [instance.name]), fail)
  if not fail and check:
    # Quick check that the disks are there
    AssertCommand(["gnt-instance", "activate-disks", instance.name])
    AssertCommand(["gnt-instance", "activate-disks", "--wait-for-sync",
                   instance.name])
    AssertCommand(["gnt-instance", "deactivate-disks", instance.name])


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestRecreateDisks(instance, inodes, othernodes):
  """gnt-instance recreate-disks

  @param instance: Instance to work on
  @param inodes: List of the current nodes of the instance
  @param othernodes: list/tuple of nodes where to temporarily recreate disks

  """
  options = qa_config.get("options", {})
  use_ialloc = options.get("use-iallocators", True)
  other_seq = ":".join([n.primary for n in othernodes])
  orig_seq = ":".join([n.primary for n in inodes])
  # These fail because the instance is running
  _AssertRecreateDisks(["-n", other_seq], instance, fail=True, destroy=False)
  if use_ialloc:
    _AssertRecreateDisks(["-I", "hail"], instance, fail=True, destroy=False)
  else:
    _AssertRecreateDisks(["-n", other_seq], instance, fail=True, destroy=False)
  AssertCommand(["gnt-instance", "stop", instance.name])
  # Disks exist: this should fail
  _AssertRecreateDisks([], instance, fail=True, destroy=False)
  # Recreate disks in place
  _AssertRecreateDisks([], instance)
  # Move disks away
  if use_ialloc:
    _AssertRecreateDisks(["-I", "hail"], instance)
    # Move disks somewhere else
    _AssertRecreateDisks(["-I", constants.DEFAULT_IALLOCATOR_SHORTCUT],
                         instance)
  else:
    _AssertRecreateDisks(["-n", other_seq], instance)
  # Move disks back
  _AssertRecreateDisks(["-n", orig_seq], instance, check=False)
  # This and InstanceCheck decoration check that the disks are working
  AssertCommand(["gnt-instance", "reinstall", "-f", instance.name])
  AssertCommand(["gnt-instance", "start", instance.name])


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceExport(instance, node):
  """gnt-backup export -n ..."""
  name = instance.name
  AssertCommand(["gnt-backup", "export", "-n", node.primary, name])
  return qa_utils.ResolveInstanceName(name)


@InstanceCheck(None, INST_DOWN, FIRST_ARG)
def TestInstanceExportWithRemove(instance, node):
  """gnt-backup export --remove-instance"""
  AssertCommand(["gnt-backup", "export", "-n", node.primary,
                 "--remove-instance", instance.name])


@InstanceCheck(INST_UP, INST_UP, FIRST_ARG)
def TestInstanceExportNoTarget(instance):
  """gnt-backup export (without target node, should fail)"""
  AssertCommand(["gnt-backup", "export", instance.name], fail=True)


@InstanceCheck(None, INST_DOWN, FIRST_ARG)
def TestInstanceImport(newinst, node, expnode, name):
  """gnt-backup import"""
  templ = constants.DT_PLAIN
  cmd = (["gnt-backup", "import",
          "--disk-template=%s" % templ,
          "--no-ip-check",
          "--src-node=%s" % expnode.primary,
          "--src-dir=%s/%s" % (pathutils.EXPORT_DIR, name),
          "--node=%s" % node.primary] +
         _GetGenericAddParameters(newinst, force_mac=constants.VALUE_GENERATE))
  cmd.append(newinst.name)
  AssertCommand(cmd)
  newinst.SetDiskTemplate(templ)


def TestBackupList(expnode):
  """gnt-backup list"""
  AssertCommand(["gnt-backup", "list", "--node=%s" % expnode.primary])

  qa_utils.GenericQueryTest("gnt-backup", query.EXPORT_FIELDS.keys(),
                            namefield=None, test_unknown=False)


def TestBackupListFields():
  """gnt-backup list-fields"""
  qa_utils.GenericQueryFieldsTest("gnt-backup", query.EXPORT_FIELDS.keys())


def TestRemoveInstanceOfflineNode(instance, snode, set_offline, set_online):
  """gtn-instance remove with an off-line node

  @param instance: instance
  @param snode: secondary node, to be set offline
  @param set_offline: function to call to set the node off-line
  @param set_online: function to call to set the node on-line

  """
  info = _GetInstanceInfo(instance.name)
  set_offline(snode)
  try:
    TestInstanceRemove(instance)
  finally:
    set_online(snode)
  # Clean up the disks on the offline node
  for minor in info["drbd-minors"][snode.primary]:
    AssertCommand(["drbdsetup", str(minor), "down"], node=snode)
  AssertCommand(["lvremove", "-f"] + info["volumes"], node=snode)
