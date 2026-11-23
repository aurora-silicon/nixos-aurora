# Print the graphics lines an install-grub.pl writes into grub.cfg for one
# GRUB EFI target: its $efiUga statement and its "Setup the graphics stack"
# block, evaluated as the script evaluates them.
use strict;
use warnings;
my ($file, $grubTargetEfi) = @ARGV;
open(my $handle, '<', $file) or die "cannot read $file: $!\n";
my $text = do { local $/; <$handle> };
my ($choice) = $text =~ /^my \$efiUga = (.*);$/m or die "$file has no \$efiUga\n";
my ($block) = $text =~ /\n(\s*# Setup the graphics stack.*?\n\s*fi\n)/s or die "$file has no graphics block\n";
my $efiUga = eval $choice;
die $@ if $@;
my $lines = eval "\"$block\"";
die $@ if $@;
print $lines;
