class Libusbmuxd < Formula
  desc "USB multiplexor library for iOS devices"
  homepage "https://www.libimobiledevice.org/"
  url "https://github.com/libimobiledevice/libusbmuxd/releases/download/2.1.1/libusbmuxd-2.1.1.tar.bz2"
  sha256 "5546f1aba1c3d1812c2b47d976312d00547d1044b84b6a461323c621f396efce"
  license all_of: ["GPL-2.0-or-later", "LGPL-2.1-or-later"]
  revision 1
  compatibility_version 1

  head do
    url "https://github.com/libimobiledevice/libusbmuxd.git", branch: "master"

    depends_on "autoconf" => :build
    depends_on "automake" => :build
    depends_on "libtool" => :build
  end

  depends_on "pkgconf" => :build
  depends_on "libimobiledevice-glue"
  depends_on "libplist"

  allow_network_access! :test

  def install
    configure = build.head? ? "./autogen.sh" : "./configure"
    system configure, "--disable-silent-rules", *std_configure_args
    system "make", "install"
  end

  test do
    source = free_port
    dest = free_port

    PTY.spawn(bin/"iproxy", "-s", "localhost", "#{source}:#{dest}") do |r, w, pid|
      assert_match "Creating listening port #{source} for device port #{dest}", r.readline
      assert_match "waiting for connection", r.readline
      TCPSocket.new("localhost", source).close
      assert_match "New connection for #{source}->#{dest}", r.readline
    ensure
      r.close
      w.close
      Process.wait(pid)
    end
  end
end
