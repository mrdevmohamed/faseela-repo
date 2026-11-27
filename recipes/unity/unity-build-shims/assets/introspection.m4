dnl Build-time stand-in for gobject-introspection's introspection.m4.
dnl GObject-Introspection is not packaged. The Unity libraries declare it as
dnl optional; this macro reports it as unavailable so that `--disable-introspection`
dnl (the default here) and the automake conditional work, and `--enable-introspection`
dnl fails loudly instead of silently producing nothing.
AC_DEFUN([GOBJECT_INTROSPECTION_CHECK],[
  AC_ARG_ENABLE([introspection],
    [AS_HELP_STRING([--enable-introspection],[not available in this build environment])],
    [],[enable_introspection=no])
  AS_IF([test "x$enable_introspection" = "xyes"],
    [AC_MSG_ERROR([GObject-Introspection is not packaged; use --disable-introspection])])
  INTROSPECTION_SCANNER=
  INTROSPECTION_COMPILER=
  INTROSPECTION_GENERATE=
  INTROSPECTION_GIRDIR=
  INTROSPECTION_TYPELIBDIR=
  INTROSPECTION_CFLAGS=
  INTROSPECTION_LIBS=
  INTROSPECTION_MAKEFILE=
  AC_SUBST([INTROSPECTION_SCANNER])
  AC_SUBST([INTROSPECTION_COMPILER])
  AC_SUBST([INTROSPECTION_GENERATE])
  AC_SUBST([INTROSPECTION_GIRDIR])
  AC_SUBST([INTROSPECTION_TYPELIBDIR])
  AC_SUBST([INTROSPECTION_CFLAGS])
  AC_SUBST([INTROSPECTION_LIBS])
  AC_SUBST([INTROSPECTION_MAKEFILE])
  AM_CONDITIONAL([HAVE_INTROSPECTION],[false])
])
AC_DEFUN([GOBJECT_INTROSPECTION_REQUIRE],[
  AC_MSG_ERROR([GObject-Introspection is not packaged in this build environment])
])
