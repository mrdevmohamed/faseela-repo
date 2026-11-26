dnl Build-time stand-in for gtk-doc's GTK_DOC_CHECK macro.
dnl The Unity libraries call GTK_DOC_CHECK from configure.ac; their API manuals
dnl are never built here, so the macro only declares the usual options and the
dnl automake conditionals as "off".
AC_DEFUN([GTK_DOC_CHECK],[
  AC_ARG_ENABLE([gtk-doc],
    [AS_HELP_STRING([--enable-gtk-doc],[accepted for compatibility; documentation is never built])],
    [],[enable_gtk_doc=no])
  AC_ARG_ENABLE([gtk-doc-html],
    [AS_HELP_STRING([--enable-gtk-doc-html],[accepted for compatibility])],
    [],[enable_gtk_doc_html=no])
  AC_ARG_ENABLE([gtk-doc-pdf],
    [AS_HELP_STRING([--enable-gtk-doc-pdf],[accepted for compatibility])],
    [],[enable_gtk_doc_pdf=no])
  enable_gtk_doc=no
  HTML_DIR='${datadir}/gtk-doc/html'
  AC_SUBST([HTML_DIR])
  AM_CONDITIONAL([HAVE_GTK_DOC],[false])
  AM_CONDITIONAL([ENABLE_GTK_DOC],[false])
  AM_CONDITIONAL([GTK_DOC_BUILD_HTML],[false])
  AM_CONDITIONAL([GTK_DOC_BUILD_PDF],[false])
  AM_CONDITIONAL([GTK_DOC_USE_LIBTOOL],[false])
  AM_CONDITIONAL([GTK_DOC_USE_REBASE],[false])
])
