import os
import re
import subprocess
import logging
import json
import uuid
from urlparse import urlparse
import shutil
import cStringIO

import tornado
from tornado import httpclient

import settings
from consts import *
from ziputil import create_zip


class BaseHandler(tornado.web.RequestHandler):
	pass


class RootHandler(BaseHandler):
	def get(self):
		self.render("root.html", supported_languages=SUPPORTED_LANGUAGES)


class GenerateThriftBindingHandler(BaseHandler):
	def _generate_temp_id(self):
		return str(uuid.uuid4()).replace("-", "")

	def _pack_result(self, path, filename, language):
		package_filename = DEFAULT_PACKAGE_NAME_TEMPLATE % (filename, language.replace(":", "_"))
		p = os.path.join(path, package_filename)
		logging.debug("Packing to " + p)
		create_zip(path, "", p, excludelist={ package_filename : None })
		return package_filename

	def _generate_bindings(self, path, filename, **kwargs):
		cmd = [
			settings.THRIFT_BIN,
			"-o %s" % path,
			"--gen %s" % kwargs["gen"],
			os.path.join(path, filename)
		]

		cmd = " ".join(cmd)

		logging.debug("Using path=" + path)
		logging.debug("Executing cmd='" + cmd + "'")

		p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
		result, error = p.communicate()
		if p.returncode != 0:
			raise Exception(result)

		paths = os.listdir(path)

		found_bindings = False
		for p in paths:
			if p.find("gen-") > -1:
				found_bindings = True
				break

		if not found_bindings:
			raise Exception(result)
				

	def _handle_request(self, response):
		if response.error:
			self.set_status(500)
			self.finish(json.dumps({ "result" : 500, "text" : "failed to retrieve file. Reasone: %s" % reponse.error }))

		language = self.get_argument("gen")

		parsed_url = urlparse(response.request.url)
		path_parts = parsed_url.path.split("/")

		filename = path_parts[-1]

		path = os.path.join(settings.TEMP_PATH, self._generate_temp_id())
		os.makedirs(path)
		try:
			f = open(os.path.join(path, filename), "wb")
			try:
				f.write(response.body)
			finally:
				f.close()

			self._generate_bindings(path, filename, gen=language)
			package_filename = self._pack_result(path, filename, language)

			self.set_header("Content-Type", "application/octet-stream")
			self.set_header("Content-Disposition","attachment; filename=%s" % package_filename)
			f = open(os.path.join(path, package_filename), "rb")
			try:
				self.write(f.read())
			finally:
				f.close()			
		finally:
			logging.debug("Removing temp path '" + path + "'")
			shutil.rmtree(path)

		self.finish()

	@tornado.web.asynchronous
	def get(self):
		url = self.get_argument("url", None)
		if not url:
			self.set_status(400)
			self.finish(json.dumps({ "result" : 400, "text" : "'url' parameter is missing" }))

		http_client = httpclient.AsyncHTTPClient()
		http_client.fetch(url, self._handle_request)

	def post(self):
		gen = self.get_argument("gen")

		first_filename = None

		path = os.path.join(settings.TEMP_PATH, self._generate_temp_id())
		os.makedirs(path)
		try:
			if len(self.request.files) > 0:
				for k in self.request.files:
					o = self.request.files[k][0]
					filename = o["filename"]

					if not first_filename:
						first_filename = filename

					f = open(os.path.join(path, filename), "wb")
					try:
						f.write(o["body"])
					finally:
						f.close()
			else:
				thrift_file_content = self.get_argument("thriftcontent")
				f = open(os.path.join(path, "file.thrift"), "w")
				try:
					f.write(thrift_file_content)
					first_filename = "file.thrift"
				finally:
					f.close()

			self._generate_bindings(path, first_filename, gen=gen)
			package_filename = self._pack_result(path, first_filename, gen)

			self.set_header("Content-Type", "application/octet-stream")
			self.set_header("Content-Disposition","attachment; filename=%s" % package_filename)
			f = open(os.path.join(path, package_filename), "rb")
			try:
				self.write(f.read())
			finally:
				f.close()
		finally:
			logging.debug("Removing temp path '" + path + "'")
			shutil.rmtree(path)

