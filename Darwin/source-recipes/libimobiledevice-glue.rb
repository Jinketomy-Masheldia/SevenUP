class LibimobiledeviceGlue < Formula
  desc "Library with common system API code for libimobiledevice projects"
  homepage "https://libimobiledevice.org/"
  url "https://github.com/libimobiledevice/libimobiledevice-glue/releases/download/1.3.3/libimobiledevice-glue-1.3.3.tar.bz2"
  sha256 "920ce01382a32695f49b23292b4979a03f0afd16c58e8755d8b7f41804acc1a9"
  license "LGPL-2.1-or-later"
  compatibility_version 1
  head "https://github.com/libimobiledevice/libimobiledevice-glue.git", branch: "master"

  depends_on "autoconf" => :build
  depends_on "automake" => :build
  depends_on "libtool" => :build
  depends_on "pkgconf" => :build
  depends_on "libplist"

  def install
    configure = build.head? ? "./autogen.sh" : "./configure"
    system configure, "--disable-silent-rules", *std_configure_args
    system "make", "install"
  end

  test do
    (testpath/"test.c").write <<~C
      #include "libimobiledevice-glue/utils.h"

      int main(int argc, char* argv[]) {
        char *uuid = generate_uuid();
        return 0;
      }
    C
    system ENV.cc, "test.c", "-L#{lib}", "-limobiledevice-glue-1.0", "-o", "test"
    system "./test"
  end
end
